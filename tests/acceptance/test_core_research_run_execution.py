from __future__ import annotations

import hashlib
from collections.abc import Callable

import pytest
from core_runtime import create_migrated_test_app as create_app
from fastapi.testclient import TestClient
from fixture_release import publish_fixture_release

import thesistrace.research_run.service as research_run_service_module
from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.publication import PublishedRef
from thesistrace.publication.serialization import canonical_json_bytes
from thesistrace.research_run import ResearchRunService
from thesistrace.research_run.result import (
    RESULT_DAILY_PARTITION_PREFIX,
    read_result_bundle,
    result_bundle_byte_budget,
)


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_queued_run_executes_publishes_and_reopens_without_reexecution() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)
    observed: list[tuple[str, str]] = []

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id, immutable_input = _admit_run(client, request_id="ticket-20-success")

        assert client.get(f"/api/research-runs/{run_id}").json()["status"] == "queued"
        processor = ResearchRunService(
            runtime.database,
            load_canonical=runtime.data.load_canonical,
            publication=runtime.publication,
            progress=lambda stage, current_run_id: observed.append(
                (stage, runtime.research_runs.get(current_run_id).status)
            ),
        )

        assert processor.process_next() is True
        assert observed[0] == ("claimed", "running")
        detail = client.get(f"/api/research-runs/{run_id}")
        assert detail.status_code == 200
        public_run = detail.json()
        assert {
            name: public_run[name]
            for name in (
                "id",
                "status",
                "definition_id",
                "definition_revision",
                "dataset_release_id",
            )
        } == {
            "id": run_id,
            "status": "succeeded",
            "definition_id": public_run["definition_id"],
            "definition_revision": 1,
            "dataset_release_id": immutable_input["dataset_release_id"],
        }
        assert set(public_run) == {
            "id",
            "status",
            "definition_id",
            "definition_revision",
            "dataset_release_id",
            "result",
        }
        assert not {
            "attempt",
            "claim",
            "lease",
            "heartbeat",
            "fence",
            "manifest",
            "object",
        }.intersection(str(public_run).lower().replace("_", " ").split())

        stored = _stored_execution(runtime.database, run_id)
        assert stored["status"] == "succeeded"
        assert stored["attempt_count"] == 1
        assert isinstance(stored["result_manifest_sha256"], str)
        assert isinstance(stored["result_provenance"], dict)
        expected_input_digest = hashlib.sha256(canonical_json_bytes(immutable_input)).hexdigest()
        assert stored["result_provenance"] == {
            "schema_version": "research-result-v1",
            "research_run_id": run_id,
            "immutable_input_sha256": expected_input_digest,
            "dataset_release_id": immutable_input["dataset_release_id"],
            "calculation_contracts": {
                "strategy": immutable_input["strategy"],
                "costs": immutable_input["costs"],
                "risk_free_rate": immutable_input["risk_free_rate"],
                "numeric_execution_contract": immutable_input["numeric_execution_contract"],
            },
            "semantic_versions": immutable_input["semantic_versions"],
        }
        bundle = runtime.publication.read(
            PublishedRef(
                manifest_sha256=stored["result_manifest_sha256"],
                kind="research.result",
                provenance=stored["result_provenance"],
            )
        )
        result = read_result_bundle(bundle)
        assert set(bundle.payloads) == {
            "factor_summary",
            "strategy_summary",
            "strategy_daily_observations",
            f"{RESULT_DAILY_PARTITION_PREFIX}000000",
            "terminal_strategy_state",
        }
        assert bundle.payloads["strategy_daily_observations"].media_type == "application/json"
        assert bundle.payloads[f"{RESULT_DAILY_PARTITION_PREFIX}000000"].media_type == (
            "application/vnd.apache.parquet"
        )
        assert set(result) == {
            "factor_summary",
            "strategy_summary",
            "strategy_daily_observations",
            "terminal_strategy_state",
        }
        assert set(result["factor_summary"]["horizons"]) == {"1", "5", "20"}
        assert all(
            "daily" not in horizon for horizon in result["factor_summary"]["horizons"].values()
        )
        assert len(result["strategy_daily_observations"]) == 504
        expected_daily_fields = {
            "session",
            "gross_nav",
            "net_nav",
            "benchmark_nav",
            "net_cash",
            "transaction_cost_cny",
            "holdings_count",
            "maximum_single_name_weight",
            "upper_limit_buy_rejections",
            "lower_limit_sell_rejections",
            "suspension_rejections",
        }
        assert all(
            set(observation) == expected_daily_fields
            for observation in result["strategy_daily_observations"]
        )
        assert "alpha_matrix" not in result
        assert "forward_labels" not in result
        assert "orders" not in result
        assert "fills" not in result
        assert _result_bundle_bytes(runtime.database, stored["result_manifest_sha256"]) <= 1_048_576

    with TestClient(create_app(settings)) as restarted_http:
        reopened = restarted_http.get(f"/api/research-runs/{run_id}")
        assert reopened.status_code == 200
        assert reopened.json()["status"] == "succeeded"
        runtime = restarted_http.app.state.core_runtime
        assert runtime.research_runs.process_next() is False
        assert _stored_execution(runtime.database, run_id)["attempt_count"] == 1
        listing = restarted_http.get("/api/research-runs").json()
        assert listing["items"][0]["status"] == "succeeded"


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_publication_failure_cannot_expose_partial_result_or_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id, _immutable_input = _admit_run(client, request_id="ticket-20-publish-fail")
        manifest_count = _publication_manifest_count(runtime.database)
        original_record: Callable[..., object] = runtime.publication.record

        def fail_after_record(*args: object, **kwargs: object) -> object:
            original_record(*args, **kwargs)
            raise RuntimeError("injected result publication failure")

        monkeypatch.setattr(runtime.publication, "record", fail_after_record)
        assert runtime.research_runs.process_next() is True

        detail = client.get(f"/api/research-runs/{run_id}").json()
        assert detail["status"] == "failed"
        stored = _stored_execution(runtime.database, run_id)
        assert stored["result_manifest_sha256"] is None
        assert stored["result_provenance"] is None
        assert stored["attempt_count"] == 1
        assert _publication_manifest_count(runtime.database) == manifest_count


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_legal_over_budget_result_leaves_no_visible_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id, _immutable_input = _admit_run(client, request_id="ticket-04-over-budget")
        manifest_count = _publication_manifest_count(runtime.database)
        original_builder = research_run_service_module.build_result_payload
        oversized_results: list[dict[str, object]] = []

        def build_oversized_result(*args: object, **kwargs: object) -> dict[str, object]:
            result = original_builder(*args, **kwargs)
            positions = [
                {
                    "instrument_id": f"equity:{index:012d}.SH",
                    "execution_shares": 100,
                    "adjusted_units": "9999999999999999999999999999999999",
                    "last_adjusted_price": "9999999999999999999999999999999999",
                }
                for index in range(12_000)
            ]
            terminal = result["terminal_strategy_state"]
            terminal["positions"] = positions
            terminal["last_daily_observation"]["holdings_count"] = len(positions)
            terminal["metric_state"]["holdings_ending"] = len(positions)
            oversized_results.append(result)
            return result

        exact_bytes: list[int] = []
        original_prepare = runtime.publication.prepare

        def observe_real_prepare(**kwargs: object):
            prepared = original_prepare(**kwargs)
            exact_bytes.append(prepared.exact_bytes)
            return prepared

        monkeypatch.setattr(
            research_run_service_module,
            "build_result_payload",
            build_oversized_result,
        )
        monkeypatch.setattr(runtime.publication, "prepare", observe_real_prepare)

        assert runtime.research_runs.process_next() is True
        assert len(oversized_results) == len(exact_bytes) == 1
        assert exact_bytes[0] > result_bundle_byte_budget(
            len(oversized_results[0]["strategy_daily_observations"])
        )

        detail = client.get(f"/api/research-runs/{run_id}").json()
        assert detail["status"] == "failed"
        stored = _stored_execution(runtime.database, run_id)
        assert stored["result_manifest_sha256"] is None
        assert stored["result_provenance"] is None
        assert _publication_manifest_count(runtime.database) == manifest_count


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_stale_execution_fence_cannot_publish_or_record_success() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id, _immutable_input = _admit_run(client, request_id="ticket-20-stale")
        manifest_count = _publication_manifest_count(runtime.database)

        def stale_after_prepare(stage: str, current_run_id: str) -> None:
            if stage != "prepared":
                return
            with runtime.database.transaction() as transaction:
                transaction.execute(
                    """
                    UPDATE research_runs.runs
                    SET status = 'cancelled', execution_fence = execution_fence + 1,
                        updated_at = now()
                    WHERE id = %s
                    """,
                    (current_run_id,),
                )

        processor = ResearchRunService(
            runtime.database,
            load_canonical=runtime.data.load_canonical,
            publication=runtime.publication,
            progress=stale_after_prepare,
        )
        assert processor.process_next() is True

        detail = client.get(f"/api/research-runs/{run_id}").json()
        assert detail["status"] == "cancelled"
        stored = _stored_execution(runtime.database, run_id)
        assert stored["result_manifest_sha256"] is None
        assert stored["result_provenance"] is None
        assert _publication_manifest_count(runtime.database) == manifest_count


def _admit_run(client: TestClient, *, request_id: str) -> tuple[str, dict[str, object]]:
    runtime = client.app.state.core_runtime
    publish_fixture_release(client)
    accepted = client.post(
        "/api/definitions/run",
        json={
            "request_id": request_id,
            "name": "Executable immutable run",
            "alpha": {
                "operator_id": "ts_mean",
                "operands": [
                    {"field_id": "price.close.adjusted"},
                    {"literal": 20},
                ],
            },
            "universe": "top1000",
            "neutralization": "industry",
            "holdings_count": 30,
            "rebalance_every_sessions": 5,
        },
    )
    assert accepted.status_code == 200
    run_id = accepted.json()["run"]["id"]
    stored = _stored_execution(runtime.database, run_id)
    assert isinstance(stored["immutable_input"], dict)
    return run_id, stored["immutable_input"]


def _drop_product_schemas(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute("DROP SCHEMA IF EXISTS research_runs CASCADE")
            transaction.execute("DROP SCHEMA IF EXISTS definitions CASCADE")
            transaction.execute("DROP SCHEMA IF EXISTS data CASCADE")
            transaction.execute("DROP SCHEMA IF EXISTS publication CASCADE")
    finally:
        database.close()


def _stored_execution(database: PostgresDatabase, run_id: str) -> dict[str, object]:
    with database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT run.status, run.immutable_input, run.result_manifest_sha256,
                   run.result_provenance,
                   (SELECT count(*) FROM research_runs.attempts AS attempt
                    WHERE attempt.run_id = run.id) AS attempt_count
            FROM research_runs.runs AS run
            WHERE run.id = %s
            """,
            (run_id,),
        ).fetchone()
    assert row is not None
    return row


def _publication_manifest_count(database: PostgresDatabase) -> int:
    with database.transaction() as transaction:
        row = transaction.execute("SELECT count(*) AS count FROM publication.manifests").fetchone()
    assert row is not None
    return int(row["count"])


def _result_bundle_bytes(database: PostgresDatabase, manifest_sha256: str) -> int:
    with database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT octet_length(manifest.manifest_bytes)
                   + coalesce(sum(object.byte_size), 0) AS exact_bytes
            FROM publication.manifests AS manifest
            LEFT JOIN publication.manifest_objects AS link
              ON link.manifest_sha256 = manifest.sha256
            LEFT JOIN publication.objects AS object
              ON object.sha256 = link.object_sha256
            WHERE manifest.sha256 = %s
            GROUP BY manifest.manifest_bytes
            """,
            (manifest_sha256,),
        ).fetchone()
    assert row is not None
    return int(row["exact_bytes"])
