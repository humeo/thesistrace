import copy
import hashlib
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pyarrow as pa
import pytest
from botocore.client import BaseClient
from botocore.exceptions import ClientError, ResponseStreamingError

from thesistrace.entrypoints.runtime import CoreSettings, open_core_runtime
from thesistrace.publication import (
    JsonPayload,
    ParquetRowsPayload,
    Publication,
    PublicationPreparationError,
    PublicationUnavailableError,
    PublicationVerificationError,
)
from thesistrace.publication.serialization import (
    ParquetWriterContract,
    canonical_json_bytes,
)
from thesistrace.research_run.result import (
    LAST_DAILY_OBSERVATION_KEYS,
    METRIC_STATE_KEYS,
    RESULT_DAILY_PARTITION_PREFIX,
    RESULT_TERMINAL_POSITION_PARTITION_PREFIX,
    STRATEGY_METRIC_KEYS,
    read_result_bundle,
    read_semantic_result_section,
    result_bundle_byte_budget,
    result_publication_payloads,
)

ROWS_CONTRACT = ParquetWriterContract(
    name="ticket-05-rows",
    version=1,
    schema=pa.schema(
        [
            pa.field("session", pa.string(), nullable=False),
            pa.field("value", pa.float64(), nullable=False),
        ]
    ),
    sort_keys=("session",),
)


@pytest.fixture(autouse=True)
def clean_publication_objects(
    core_settings: CoreSettings,
    rustfs_admin: BaseClient,
) -> Iterator[None]:
    _clear_bucket(rustfs_admin, core_settings.s3_bucket)
    yield
    _clear_bucket(rustfs_admin, core_settings.s3_bucket)


def test_prepare_is_canonical_idempotent_and_verified(core_settings: CoreSettings) -> None:
    payloads = {
        "metadata": JsonPayload({"z": 3, "alpha": "量化"}),
        "rows": ParquetRowsPayload(
            rows=(
                {"session": "2026-01-06", "value": 2.0},
                {"session": "2026-01-05", "value": 1.0},
            ),
            contract=ROWS_CONTRACT,
        ),
    }
    provenance = {"source": "fixture", "sessions": ["2026-01-05", "2026-01-06"]}

    with open_core_runtime(core_settings) as runtime:
        first = runtime.publication.prepare(
            kind="dataset.fixture",
            payloads=payloads,
            provenance=provenance,
        )
        second = runtime.publication.prepare(
            kind="dataset.fixture",
            payloads={
                "rows": ParquetRowsPayload(
                    rows=tuple(reversed(payloads["rows"].rows)),
                    contract=ROWS_CONTRACT,
                ),
                "metadata": JsonPayload({"alpha": "量化", "z": 3}),
            },
            provenance={"sessions": ["2026-01-05", "2026-01-06"], "source": "fixture"},
        )

        assert first.manifest_sha256 == second.manifest_sha256
        assert first.object_count == second.object_count == 2
        assert "key" not in repr(first).lower()

        verified = runtime.publication.verify_prepared(second)
        assert verified.kind == "dataset.fixture"
        assert verified.manifest_sha256 == first.manifest_sha256
        assert verified.provenance == provenance
        assert verified.payloads["metadata"].content == canonical_json_bytes(
            {"alpha": "量化", "z": 3}
        )
        assert verified.payloads["rows"].media_type == "application/vnd.apache.parquet"


def test_research_result_preparation_uses_bounded_collection_objects(
    core_settings: CoreSettings,
) -> None:
    result = _legal_result()
    with open_core_runtime(core_settings) as runtime:
        first = runtime.publication.prepare(
            kind="research.result",
            payloads=result_publication_payloads(
                result, research_kind="strategy_backtest"
            ),
            provenance={"research_run_id": "run-result-codec"},
        )
        second = runtime.publication.prepare(
            kind="research.result",
            payloads=result_publication_payloads(
                result, research_kind="strategy_backtest"
            ),
            provenance={"research_run_id": "run-result-codec"},
        )

        assert first.manifest_sha256 == second.manifest_sha256
        assert first.payload_sha256s == second.payload_sha256s
        assert first.object_count == 6
        assert set(first.payload_sha256s) == {
            "factor_summary",
            "strategy_summary",
            "strategy_daily_observations",
            f"{RESULT_DAILY_PARTITION_PREFIX}000000",
            "terminal_strategy_state",
            "terminal_positions",
        }
        assert first.exact_bytes <= result_bundle_byte_budget(1)
        assert (
            read_result_bundle(
                runtime.publication.verify_prepared(second),
                research_kind="strategy_backtest",
            )
            == result
        )


def test_semantic_result_sections_read_only_bounded_real_rustfs_objects(
    core_settings: CoreSettings,
    rustfs_admin: BaseClient,
) -> None:
    result = _legal_result()
    observation = result["strategy_daily_observations"][0]
    result["strategy_daily_observations"] = [
        {**observation, "session": f"{index:06d}"} for index in range(505)
    ]
    position = {
        "instrument_id": "equity:000000.SZ",
        "execution_shares": 100,
        "adjusted_units": "100",
        "last_adjusted_price": "10",
    }
    result["terminal_strategy_state"]["positions"] = [
        {**position, "instrument_id": f"equity:{index:06d}.SZ"}
        for index in range(101)
    ]

    with open_core_runtime(core_settings) as runtime:
        prepared = runtime.publication.prepare(
            kind="research.result",
            payloads=result_publication_payloads(
                result,
                research_kind="strategy_backtest",
            ),
            provenance={"research_run_id": "run-selective-result"},
        )
        with runtime.database.transaction() as transaction:
            published_ref = runtime.publication.record(transaction, prepared)

        observed_digests: list[str] = []

        def record_get_object(params: dict[str, object], **_kwargs: object) -> None:
            observed_digests.append(str(params["Key"]).rsplit("/", 1)[-1])

        event_name = "before-parameter-build.s3.GetObject"
        rustfs_admin.meta.events.register(event_name, record_get_object)
        publication = Publication(
            runtime.database,
            rustfs_admin,
            bucket=core_settings.s3_bucket,
        )
        payload_digests = prepared.payload_sha256s
        try:
            factor = read_semantic_result_section(
                publication,
                published_ref,
                research_kind="strategy_backtest",
                section="factor",
            )
            assert factor.next_after is None
            assert observed_digests == [payload_digests["factor_summary"]]

            observed_digests.clear()
            terminal = read_semantic_result_section(
                publication,
                published_ref,
                research_kind="strategy_backtest",
                section="terminal_strategy_state",
            )
            assert set(terminal.value) == {
                "session",
                "gross_cash",
                "net_cash",
                "gross_nav",
                "net_nav",
                "benchmark_nav",
                "cumulative_transaction_cost",
                "rebalance_phase",
                "pending_signal",
            }
            assert observed_digests == [payload_digests["terminal_strategy_state"]]

            observed_digests.clear()
            observations = read_semantic_result_section(
                publication,
                published_ref,
                research_kind="strategy_backtest",
                section="strategy_observations",
                limit=50,
            )
            assert len(observations.value) == 50
            assert observations.next_after == "000049"
            assert observed_digests == [
                payload_digests["strategy_daily_observations"],
                payload_digests[f"{RESULT_DAILY_PARTITION_PREFIX}000000"],
            ]

            observed_digests.clear()
            positions = read_semantic_result_section(
                publication,
                published_ref,
                research_kind="strategy_backtest",
                section="terminal_positions",
                limit=50,
            )
            assert len(positions.value) == 50
            assert positions.next_after == "equity:000049.SZ"
            assert observed_digests == [
                payload_digests["terminal_positions"],
                payload_digests[f"{RESULT_TERMINAL_POSITION_PARTITION_PREFIX}000000"],
                payload_digests[f"{RESULT_TERMINAL_POSITION_PARTITION_PREFIX}000001"],
            ]

            observed_digests.clear()
            provenance = read_semantic_result_section(
                publication,
                published_ref,
                research_kind="strategy_backtest",
                section="provenance",
            )
            assert provenance.value == published_ref.provenance
            assert observed_digests == []

            with pytest.raises(
                PublicationVerificationError,
                match="Selected Publication payload does not exist",
            ):
                publication.read_selected(
                    published_ref,
                    frozenset({"missing_payload"}),
                )
            assert observed_digests == []
        finally:
            rustfs_admin.meta.events.unregister(event_name, record_get_object)
            with runtime.database.transaction() as transaction:
                transaction.execute(
                    "DELETE FROM publication.manifest_objects WHERE manifest_sha256 = %s",
                    (prepared.manifest_sha256,),
                )
                transaction.execute(
                    "DELETE FROM publication.manifests WHERE sha256 = %s",
                    (prepared.manifest_sha256,),
                )
                for digest in payload_digests.values():
                    transaction.execute(
                        """
                        DELETE FROM publication.objects AS object
                        WHERE object.sha256 = %s
                          AND NOT EXISTS (
                              SELECT 1
                              FROM publication.manifest_objects AS link
                              WHERE link.object_sha256 = object.sha256
                          )
                        """,
                        (digest,),
                    )


def test_all_payloads_are_serialized_before_any_upload(
    core_settings: CoreSettings,
    rustfs_admin: BaseClient,
) -> None:
    valid_content = canonical_json_bytes({"must_not_upload": "ticket-05"})

    with open_core_runtime(core_settings) as runtime:
        with pytest.raises(PublicationPreparationError) as captured:
            runtime.publication.prepare(
                kind="serialization.atomicity",
                payloads={
                    "a_valid": JsonPayload({"must_not_upload": "ticket-05"}),
                    "z_invalid": ParquetRowsPayload(
                        rows=({"session": "2026-01-05", "value": "not-a-float"},),
                        contract=ROWS_CONTRACT,
                    ),
                },
                provenance={"ticket": 5},
            )

    assert str(captured.value) == "Parquet payload violates its contract"
    assert not _bucket_contains_content(rustfs_admin, core_settings.s3_bucket, valid_content)


@pytest.mark.parametrize(
    ("code", "status", "expected_type"),
    [
        ("ServiceUnavailable", 503, PublicationUnavailableError),
        ("AccessDenied", 403, PublicationPreparationError),
    ],
)
def test_bucket_failures_distinguish_transient_from_deterministic_errors(
    core_settings: CoreSettings,
    monkeypatch: pytest.MonkeyPatch,
    code: str,
    status: int,
    expected_type: type[Exception],
) -> None:
    def fail_head_bucket(**_arguments: object) -> None:
        raise ClientError(
            {
                "Error": {"Code": code},
                "ResponseMetadata": {"HTTPStatusCode": status},
            },
            "HeadBucket",
        )

    with open_core_runtime(core_settings) as runtime:
        monkeypatch.setattr(runtime.publication._s3, "head_bucket", fail_head_bucket)
        with pytest.raises(expected_type) as captured:
            runtime.publication.prepare(
                kind="classification.probe",
                payloads={"only": JsonPayload({"valid": True})},
                provenance={"ticket": 23},
            )

    assert isinstance(captured.value, PublicationUnavailableError) is (status >= 500)


@pytest.mark.parametrize("damage", ["missing", "truncated", "substituted"])
def test_verification_rejects_damaged_object_without_a_bundle(
    core_settings: CoreSettings,
    rustfs_admin: BaseClient,
    damage: str,
) -> None:
    expected = canonical_json_bytes({"case": damage, "value": "0123456789"})

    with open_core_runtime(core_settings) as runtime:
        prepared = runtime.publication.prepare(
            kind=f"verification.{damage}",
            payloads={"only": JsonPayload({"case": damage, "value": "0123456789"})},
            provenance={"ticket": 5},
        )
        target_key = _find_key_with_content(rustfs_admin, core_settings.s3_bucket, expected)
        if damage == "missing":
            rustfs_admin.delete_object(Bucket=core_settings.s3_bucket, Key=target_key)
        elif damage == "truncated":
            rustfs_admin.put_object(
                Bucket=core_settings.s3_bucket,
                Key=target_key,
                Body=expected[:-1],
            )
        else:
            rustfs_admin.put_object(
                Bucket=core_settings.s3_bucket,
                Key=target_key,
                Body=b"x" * len(expected),
            )

        with pytest.raises(PublicationVerificationError):
            runtime.publication.verify_prepared(prepared)


def test_prepare_never_overwrites_a_conflicting_content_address(
    core_settings: CoreSettings,
    rustfs_admin: BaseClient,
) -> None:
    expected = canonical_json_bytes({"immutable": True})

    with open_core_runtime(core_settings) as runtime:
        prepared = runtime.publication.prepare(
            kind="immutability.probe",
            payloads={"only": JsonPayload({"immutable": True})},
            provenance={"ticket": 5},
        )
        target_key = _find_key_with_content(rustfs_admin, core_settings.s3_bucket, expected)
        substitute = b"!" * len(expected)
        rustfs_admin.put_object(
            Bucket=core_settings.s3_bucket,
            Key=target_key,
            Body=substitute,
        )

        with pytest.raises(PublicationVerificationError):
            runtime.publication.prepare(
                kind="immutability.probe",
                payloads={"only": JsonPayload({"immutable": True})},
                provenance={"ticket": 5},
            )
        stored = rustfs_admin.get_object(
            Bucket=core_settings.s3_bucket,
            Key=target_key,
        )["Body"].read()
        assert stored == substitute
        assert hashlib.sha256(stored).hexdigest() != prepared.payload_sha256s["only"]


def test_concurrent_prepare_uses_conditional_create_without_overwrite(
    core_settings: CoreSettings,
    rustfs_admin: BaseClient,
) -> None:
    expected = canonical_json_bytes({"race": "ticket-05"})
    barrier = Barrier(2)

    class ConcurrentPutClient:
        def __getattr__(self, name: str):
            return getattr(rustfs_admin, name)

        def put_object(self, **arguments):
            if arguments.get("Body") == expected:
                barrier.wait(timeout=5)
            return rustfs_admin.put_object(**arguments)

    with open_core_runtime(core_settings) as runtime:
        runtime.publication.prepare(
            kind="race.bucket.warmup",
            payloads={"warmup": JsonPayload({"warmup": True})},
            provenance={"ticket": 5},
        )
        publication = Publication(
            runtime.database,
            ConcurrentPutClient(),
            bucket=core_settings.s3_bucket,
        )

        def prepare_once() -> str:
            return publication.prepare(
                kind="race.concurrent",
                payloads={"only": JsonPayload({"race": "ticket-05"})},
                provenance={"ticket": 5},
            ).manifest_sha256

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _index: prepare_once(), range(2)))

    assert results[0] == results[1]
    target_key = _find_key_with_content(rustfs_admin, core_settings.s3_bucket, expected)
    stored = rustfs_admin.get_object(
        Bucket=core_settings.s3_bucket,
        Key=target_key,
    )["Body"].read()
    assert stored == expected


@pytest.mark.parametrize("operation", ["prepare", "verify"])
def test_transient_response_stream_failure_is_retried_at_read_boundary(
    core_settings: CoreSettings,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    payloads = {"only": JsonPayload({"stream": "retry"})}

    with open_core_runtime(core_settings) as runtime:
        prepared = runtime.publication.prepare(
            kind="stream.retry",
            payloads=payloads,
            provenance={"ticket": 49},
        )
        original_get_object = runtime.publication._s3.get_object
        calls = 0
        failed_body = _FailingResponseBody()

        def fail_first_read(**arguments: object) -> object:
            nonlocal calls
            calls += 1
            if calls == 1:
                return {"Body": failed_body}
            return original_get_object(**arguments)

        monkeypatch.setattr(runtime.publication._s3, "get_object", fail_first_read)
        if operation == "prepare":
            runtime.publication.prepare(
                kind="stream.retry",
                payloads=payloads,
                provenance={"ticket": 49},
            )
        else:
            runtime.publication.verify_prepared(prepared)

    assert calls == 2
    assert failed_body.closed is True


def test_transient_response_stream_retries_are_bounded(
    core_settings: CoreSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with open_core_runtime(core_settings) as runtime:
        prepared = runtime.publication.prepare(
            kind="stream.exhaustion",
            payloads={"only": JsonPayload({"stream": "exhaustion"})},
            provenance={"ticket": 49},
        )
        calls = 0
        failed_bodies: list[_FailingResponseBody] = []

        def fail_every_read(**_arguments: object) -> object:
            nonlocal calls
            calls += 1
            body = _FailingResponseBody()
            failed_bodies.append(body)
            return {"Body": body}

        monkeypatch.setattr(runtime.publication._s3, "get_object", fail_every_read)
        with pytest.raises(PublicationUnavailableError) as captured:
            runtime.publication.verify_prepared(prepared)

    assert calls == 3
    assert all(body.closed for body in failed_bodies)
    assert str(captured.value) == "Publication object read is temporarily unavailable"


class _FailingResponseBody:
    def __init__(self) -> None:
        self.closed = False

    def read(self) -> bytes:
        raise ResponseStreamingError(error=RuntimeError("incomplete response stream"))

    def close(self) -> None:
        self.closed = True


def _find_key_with_content(s3: BaseClient, bucket: str, expected: bytes) -> str:
    response = s3.list_objects_v2(Bucket=bucket)
    for item in response.get("Contents", []):
        key = item["Key"]
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        if body == expected:
            return str(key)
    raise AssertionError("test object was not uploaded")


def _bucket_contains_content(s3: BaseClient, bucket: str, expected: bytes) -> bool:
    response = s3.list_objects_v2(Bucket=bucket)
    return any(
        s3.get_object(Bucket=bucket, Key=item["Key"])["Body"].read() == expected
        for item in response.get("Contents", [])
    )


def _clear_bucket(s3: BaseClient, bucket: str) -> None:
    try:
        response = s3.list_objects_v2(Bucket=bucket)
    except ClientError as error:
        if str(error.response.get("Error", {}).get("Code", "")) in {
            "404",
            "NoSuchBucket",
            "NotFound",
        }:
            return
        raise
    objects = [{"Key": item["Key"]} for item in response.get("Contents", [])]
    if objects:
        s3.delete_objects(Bucket=bucket, Delete={"Objects": objects})


def _legal_result() -> dict[str, object]:
    correlation = {
        "icir": None,
        "mean": None,
        "positive_fraction": None,
        "sample_deviation": None,
        "valid_session_count": 0,
    }
    horizons = {
        str(horizon): {
            "horizon": horizon,
            "alpha_checksum": "a" * 64,
            "label_checksum": "b" * 64,
            "source_checksum": "c" * 64,
            "summary": {
                "ic": copy.deepcopy(correlation),
                "quantile_returns": {name: None for name in ("q1", "q2", "q3", "q4", "q5")},
                "rank_ic": copy.deepcopy(correlation),
                "top_bottom_return": None,
            },
            "coverage": {
                "signal_session_count": 1,
                "ic_valid_session_count": 0,
                "rank_ic_valid_session_count": 0,
                "quantile_valid_session_count": 0,
            },
        }
        for horizon in (1, 5, 20)
    }
    metrics = {name: None for name in STRATEGY_METRIC_KEYS}
    metrics.update(
        {
            "cash_ratio": {
                "ending": 1.0,
                "maximum": {"session": "2024-01-02", "value": 1.0},
                "mean": 1.0,
            },
            "holdings_count": {"ending": 0, "maximum": 0, "mean": 0.0, "minimum": 0},
            "market_rejections": {"lower_limit_sell": 0, "suspension": 0, "upper_limit_buy": 0},
            "maximum_drawdown": {
                "peak_session": "2024-01-02",
                "recovery_session": None,
                "trough_session": "2024-01-02",
                "unrecovered": False,
                "value": 0.0,
            },
            "maximum_single_name_weight": {
                "ending": 0.0,
                "period_maximum": {"session": "2024-01-02", "value": 0.0},
            },
            "transaction_costs": {"cumulative_amount": 0.0, "ratio": 0.0, "return_drag": 0.0},
            "turnover": {"annualized": None, "average_rebalance": None},
        }
    )
    last_daily = {name: 0 for name in LAST_DAILY_OBSERVATION_KEYS}
    last_daily.update(
        {
            "benchmark_nav": "1",
            "cumulative_transaction_cost": "0",
            "cycle_type": "terminal_valuation",
            "execution_rounding_residual": "0",
            "gross_cash": "1e+7",
            "gross_nav": "1e+7",
            "net_cash": "1e+7",
            "net_nav": "1e+7",
            "pre_trade_gross_nav": "1e+7",
            "pre_trade_net_nav": "1e+7",
            "rebalance": False,
            "session": "2024-01-02",
            "valuation_events": [],
        }
    )
    metric_state = {name: 0 for name in METRIC_STATE_KEYS}
    metric_state.update(
        {
            "contract": "strategy-metric-state-v1",
            "first_gross_nav": "1e+7",
            "first_net_nav": "1e+7",
            "first_benchmark_nav": "1",
            "peak_net_nav": "1e+7",
            "peak_session": "2024-01-02",
            "worst_drawdown": "0",
            "worst_peak_nav": "1e+7",
            "worst_peak_session": "2024-01-02",
            "worst_trough_session": "2024-01-02",
            "worst_recovery_session": None,
            "weight_maximum_session": "2024-01-02",
            "cash_maximum_session": "2024-01-02",
            "last_gross_nav": "1e+7",
            "last_net_nav": "1e+7",
            "last_benchmark_nav": "1",
            "last_session": "2024-01-02",
            "cumulative_cost": "0",
        }
    )
    return {
        "factor_summary": {"horizons": horizons},
        "strategy_summary": {
            "alpha_checksum": "a" * 64,
            "initial_cash_cny": "1e+7",
            "source_checksum": "c" * 64,
            "metrics": metrics,
            "benchmark": {
                "universe": "manual",
                "methodology": "selected_universe_equal_weight",
            },
        },
        "strategy_daily_observations": [
            {
                "session": "2024-01-02",
                "gross_nav": "1e+7",
                "net_nav": "1e+7",
                "benchmark_nav": "1",
                "net_cash": "1e+7",
                "transaction_cost_cny": "0",
                "holdings_count": 0,
                "maximum_single_name_weight": 0.0,
                "upper_limit_buy_rejections": 0,
                "lower_limit_sell_rejections": 0,
                "suspension_rejections": 0,
            }
        ],
        "terminal_strategy_state": {
            "session": "2024-01-02",
            "gross_cash": "1e+7",
            "net_cash": "1e+7",
            "gross_nav": "1e+7",
            "net_nav": "1e+7",
            "benchmark_nav": "1",
            "cumulative_transaction_cost": "0",
            "positions": [],
            "rebalance_phase": {
                "origin_session": "2024-01-02",
                "report_session_count": 1,
                "rebalance_interval": 1,
                "completed_intervals": 0,
            },
            "pending_signal": None,
            "last_daily_observation": last_daily,
            "metric_state": metric_state,
        },
    }
