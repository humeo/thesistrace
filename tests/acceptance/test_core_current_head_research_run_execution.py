from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread

import pytest
from core_runtime import create_migrated_test_app as create_app
from core_runtime import drop_product_schemas
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase
from thesistrace.data import DatasetLifecycle, MountedGenerationStore
from thesistrace.entrypoints.migrations import migrate_core
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.fixture import build_minimal_canonical_fixture
from thesistrace.publication import PublicationVerificationError, PublishedRef
from thesistrace.research_kernel import RunInput, run
from thesistrace.research_run import ResearchRunService
from thesistrace.research_run.result import build_result_payload, read_result_bundle


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_attempt_uses_the_head_current_when_execution_starts(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    migrate_core(settings.database_url)
    sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    head_a = _publish_head(settings, sessions=sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/definitions/run",
            json=_run_command("attempt-start-head"),
        )
        assert accepted.status_code == 200
        run_id = accepted.json()["run"]["id"]
        head_b = _publish_head(
            settings,
            sessions=sessions,
            price_offset=1,
            expected_manifest=head_a,
        )

        assert client.app.state.core_runtime.research_runs.process_next() is True

        detail = client.get(f"/api/research-runs/{run_id}")
        assert detail.status_code == 200
        public_run = detail.json()
        assert public_run["status"] == "succeeded"
        assert set(public_run) == {
            "id",
            "status",
            "definition_id",
            "definition_revision",
            "start_date",
            "end_date",
            "result",
        }
        assert set(public_run["result"]) == {"factor", "strategy", "provenance"}
        assert set(public_run["result"]["provenance"]) == {
            "schema_version",
            "research_run_id",
            "immutable_input_sha256",
            "calculation_contracts",
            "semantic_versions",
        }
        assert len(public_run["result"]["strategy"]["observations"]) == 3
        assert "generation" not in str(public_run).lower()

        stored = _stored_execution(settings, run_id)
        assert stored["attempt_data_generation_id"] == head_b
        assert stored["attempt_data_through_session"].isoformat() == sessions[-1]
        assert stored["result_provenance"]["data_generation_id"] == head_b
        assert stored["result_provenance"]["data_through_session"] == sessions[-1]
        assert stored["active_pin_count"] == 0

    with TestClient(create_app(settings)) as restarted:
        reopened = restarted.get(f"/api/research-runs/{run_id}")
        assert reopened.status_code == 200
        assert reopened.json() == public_run
        assert restarted.app.state.core_runtime.research_runs.process_next() is False
        assert _stored_execution(settings, run_id)["attempt_count"] == 1


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_attempt_keeps_its_pinned_generation_when_head_moves(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    migrate_core(settings.database_url)
    sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    head_a = _publish_head(settings, sessions=sessions, price_offset=0)
    canonical_a = MountedGenerationStore(settings.data_mount).open_generation(head_a).canonical
    claimed = Event()
    continue_execution = Event()

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/definitions/run",
            json=_run_command("attempt-pinned-head"),
        )
        run_id = accepted.json()["run"]["id"]
        runtime = client.app.state.core_runtime

        def barrier(stage: str, _run_id: str) -> None:
            if stage == "claimed":
                claimed.set()
                assert continue_execution.wait(timeout=5)

        processor = ResearchRunService(
            runtime.database,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            publication=runtime.publication,
            progress=barrier,
        )
        worker = Thread(target=processor.process_next)
        worker.start()
        assert claimed.wait(timeout=5)
        assert client.get(f"/api/research-runs/{run_id}").json()["status"] == "running"
        head_b = _publish_head(
            settings,
            sessions=sessions,
            price_offset=9,
            expected_manifest=head_a,
        )
        continue_execution.set()
        worker.join(timeout=10)
        assert not worker.is_alive()

        stored = _stored_execution(settings, run_id)
        assert stored["attempt_data_generation_id"] == head_a
        assert stored["attempt_data_generation_id"] != head_b
        actual = read_result_bundle(
            runtime.publication.read(
                PublishedRef(
                    manifest_sha256=str(stored["result_manifest_sha256"]),
                    kind="research.result",
                    provenance=stored["result_provenance"],
                )
            )
        )
        expected = build_result_payload(
            run(_kernel_input(canonical_a, sessions=sessions)),
            rebalance_interval=1,
            universe="top300",
        )
        assert actual == expected
        assert stored["active_pin_count"] == 0


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_insufficient_warmup_is_one_terminal_domain_failure(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    migrate_core(settings.database_url)
    sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    _publish_head(settings, sessions=sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/definitions/run",
            json=_run_command(
                "attempt-insufficient-warmup",
                alpha={
                    "operator_id": "ts_mean",
                    "operands": [
                        {"field_id": "price.close.adjusted"},
                        {"literal": 2},
                    ],
                },
            ),
        )
        run_id = accepted.json()["run"]["id"]

        assert client.app.state.core_runtime.research_runs.process_next() is True
        assert client.app.state.core_runtime.research_runs.process_next() is False

        detail = client.get(f"/api/research-runs/{run_id}").json()
        assert detail == {
            "id": run_id,
            "status": "failed",
            "definition_id": detail["definition_id"],
            "definition_revision": 1,
            "start_date": sessions[0],
            "end_date": sessions[-1],
            "failure_reason": (
                "Selected data does not contain the complete Calculation Warm-up."
            ),
        }
        stored = _stored_execution(settings, run_id)
        assert stored["attempt_count"] == 1
        assert stored["attempt_failure_reason"] == "InsufficientCalculationWarmup"
        assert stored["result_manifest_sha256"] is None
        assert stored["result_provenance"] is None
        assert stored["active_pin_count"] == 0


@pytest.mark.parametrize("session_count", [1, 2])
@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_short_attempt_publishes_exact_period_and_complete_terminal_state(
    tmp_path: Path,
    session_count: int,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    migrate_core(settings.database_url)
    sessions = ("2026-08-03", "2026-08-04")[:session_count]
    _publish_head(settings, sessions=sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/definitions/run",
            json=_run_command(
                f"attempt-short-{session_count}",
                start_date=sessions[0],
                end_date=sessions[-1],
            ),
        )
        run_id = accepted.json()["run"]["id"]
        runtime = client.app.state.core_runtime

        assert runtime.research_runs.process_next() is True

        stored = _stored_execution(settings, run_id)
        result = read_result_bundle(
            runtime.publication.read(
                PublishedRef(
                    manifest_sha256=str(stored["result_manifest_sha256"]),
                    kind="research.result",
                    provenance=stored["result_provenance"],
                )
            )
        )
        observations = result["strategy_daily_observations"]
        assert [row["session"] for row in observations] == list(sessions)
        for horizon in result["factor_summary"]["horizons"].values():
            assert horizon["summary"]["ic"]["mean"] is None
            assert horizon["summary"]["rank_ic"]["mean"] is None
            assert horizon["coverage"]["ic_valid_session_count"] == 0
            assert horizon["coverage"]["rank_ic_valid_session_count"] == 0
        strategy_metrics = result["strategy_summary"]["metrics"]
        assert strategy_metrics["annualized_volatility"] is None
        assert strategy_metrics["sharpe"] is None
        terminal = result["terminal_strategy_state"]
        assert terminal["session"] == sessions[-1]
        assert terminal["last_daily_observation"]["session"] == sessions[-1]
        assert terminal["rebalance_phase"]["report_session_count"] == session_count
        assert terminal["metric_state"]["session_count"] == session_count
        assert isinstance(terminal["positions"], list)
        assert stored["active_pin_count"] == 0


@pytest.mark.parametrize("incompatibility", ["coverage", "field"])
@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_attempt_revalidates_the_selected_generation(
    tmp_path: Path,
    incompatibility: str,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    migrate_core(settings.database_url)
    sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    head_a = _publish_head(settings, sessions=sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/definitions/run",
            json=_run_command(f"attempt-revalidate-{incompatibility}"),
        )
        run_id = accepted.json()["run"]["id"]
        replacement_sessions = sessions[1:] if incompatibility == "coverage" else sessions
        _publish_head(
            settings,
            sessions=replacement_sessions,
            price_offset=2,
            expected_manifest=head_a,
            available_field_id=(
                "market.volume.shares"
                if incompatibility == "field"
                else "price.close.adjusted"
            ),
        )

        assert client.app.state.core_runtime.research_runs.process_next() is True
        assert client.app.state.core_runtime.research_runs.process_next() is False

        detail = client.get(f"/api/research-runs/{run_id}").json()
        assert detail["status"] == "failed"
        assert detail["start_date"] == sessions[0]
        assert detail["end_date"] == sessions[-1]
        assert detail["failure_reason"] == (
            "Current data cannot execute the requested Research Period."
        )
        stored = _stored_execution(settings, run_id)
        assert stored["attempt_count"] == 1
        assert stored["attempt_failure_reason"] == "SelectedDataInvalid"
        assert stored["result_manifest_sha256"] is None
        assert stored["active_pin_count"] == 0


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_publication_failure_is_atomic_and_releases_the_generation_pin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    migrate_core(settings.database_url)
    sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    _publish_head(settings, sessions=sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/definitions/run",
            json=_run_command("attempt-publication-failure"),
        )
        run_id = accepted.json()["run"]["id"]
        runtime = client.app.state.core_runtime
        manifest_count = _publication_manifest_count(settings)
        original_record = runtime.publication.record

        def fail_after_manifest_record(*args: object, **kwargs: object) -> object:
            original_record(*args, **kwargs)
            raise RuntimeError("injected final-state failure")

        monkeypatch.setattr(runtime.publication, "record", fail_after_manifest_record)

        assert runtime.research_runs.process_next() is True

        detail = client.get(f"/api/research-runs/{run_id}").json()
        assert detail["status"] == "failed"
        assert "result" not in detail
        stored = _stored_execution(settings, run_id)
        assert stored["attempt_count"] == 1
        assert stored["result_manifest_sha256"] is None
        assert stored["result_provenance"] is None
        assert stored["active_pin_count"] == 0
        assert _publication_manifest_count(settings) == manifest_count


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_result_read_failure_stays_sanitized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    migrate_core(settings.database_url)
    sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    _publish_head(settings, sessions=sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/definitions/run",
            json=_run_command("attempt-result-read-failure"),
        )
        run_id = accepted.json()["run"]["id"]
        runtime = client.app.state.core_runtime
        assert runtime.research_runs.process_next() is True

        def fail_read(_published_ref: object) -> object:
            raise PublicationVerificationError(
                "private bucket checksum mismatch at secret/object/key"
            )

        monkeypatch.setattr(runtime.publication, "read", fail_read)
        response = client.get(f"/api/research-runs/{run_id}")

        assert response.status_code == 503
        assert response.json() == {"detail": "ResearchRun Result unavailable"}
        assert "checksum" not in response.text.lower()
        assert "bucket" not in response.text.lower()
        assert "object" not in response.text.lower()


def _run_command(
    request_id: str,
    *,
    alpha: dict[str, object] | None = None,
    start_date: str = "2026-08-03",
    end_date: str = "2026-08-05",
) -> dict[str, object]:
    return {
        "request_id": request_id,
        "name": "Attempt-scoped current data",
        "start_date": start_date,
        "end_date": end_date,
        "alpha": alpha or {"field_id": "price.close.adjusted"},
        "universe": "top300",
        "neutralization": "none",
        "holdings_count": 1,
        "rebalance_every_sessions": 1,
    }


def _canonical(
    sessions: tuple[str, ...],
    *,
    price_offset: int,
    available_field_id: str,
) -> dict[str, object]:
    template = build_minimal_canonical_fixture(price_offset=price_offset)
    instrument_id = str(template["instruments"][0]["instrument_id"])
    price = template["prices"][0]
    state = template["trading_states"][0]
    limit = template["price_limits"][0]
    universe = {"instrument_ids": [instrument_id], "status": "available"}
    return {
        **template,
        "field_catalog": [
            {
                **template["field_catalog"][0],
                "name": (
                    "close_adj"
                    if available_field_id == "price.close.adjusted"
                    else "volume_shares"
                ),
                "field_id": available_field_id,
            }
        ],
        "research_calendar": list(sessions),
        "prices": [{**price, "session": session} for session in sessions],
        "trading_states": [{**state, "session": session} for session in sessions],
        "price_limits": [{**limit, "session": session} for session in sessions],
        "base_pool": [
            {"session": session, "instrument_ids": [instrument_id]} for session in sessions
        ],
        "liquidity_universes": {
            name: [{"session": session, **universe} for session in sessions]
            for name in ("top300", "top1000", "top2000", "top3000")
        },
    }


def _publish_head(
    settings: CoreSettings,
    *,
    sessions: tuple[str, ...],
    price_offset: int,
    expected_manifest: str | None = None,
    available_field_id: str = "price.close.adjusted",
) -> str:
    generation = MountedGenerationStore(settings.data_mount).materialize(
        _canonical(
            sessions,
            price_offset=price_offset,
            available_field_id=available_field_id,
        ),
        prepared_at=datetime(2026, 8, 9, price_offset, tzinfo=UTC),
        source_name="attempt-execution-test",
        source_lineage={"price_offset": price_offset},
    )
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        lifecycle = DatasetLifecycle(database, settings.data_mount)
        operation_id = f"attempt-execution-{price_offset}"
        lifecycle.protect_candidate(
            operation_id=operation_id,
            generation_manifest_sha256=generation.manifest_sha256,
            lease_seconds=60,
        )
        lifecycle.compare_and_swap_head(
            expected_generation_manifest_sha256=expected_manifest,
            candidate_generation_manifest_sha256=generation.manifest_sha256,
            operation_id=operation_id,
        )
    finally:
        database.close()
    return generation.manifest_sha256


def _kernel_input(
    canonical: dict[str, object],
    *,
    sessions: tuple[str, ...],
) -> RunInput:
    return RunInput(
        canonical_data=canonical,
        alpha_expression={"field_id": "price.close.adjusted"},
        field_bindings={"price.close.adjusted": "close_adj"},
        universe="top300",
        neutralization="none",
        holdings_count=1,
        rebalance_interval=1,
        initial_cash_cny="10000000",
        commission_rate_all_in="0.0003",
        commission_min_cny="5",
        stamp_duty_sell_rate="0.0005",
        transfer_fee_rate="0.00001",
        research_start_session=sessions[0],
        research_end_session=sessions[-1],
    )


def _stored_execution(settings: CoreSettings, run_id: str) -> dict[str, object]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT run.status, run.result_manifest_sha256, run.result_provenance,
                       attempt.data_generation_id AS attempt_data_generation_id,
                       attempt.data_through_session AS attempt_data_through_session,
                       attempt.failure_reason AS attempt_failure_reason,
                       (SELECT count(*)
                        FROM research_runs.attempts
                        WHERE run_id = run.id) AS attempt_count,
                       (SELECT count(*)
                        FROM data.generation_pins
                        WHERE status = 'active') AS active_pin_count
                FROM research_runs.runs AS run
                JOIN research_runs.attempts AS attempt ON attempt.run_id = run.id
                WHERE run.id = %s
                """,
                (run_id,),
            ).fetchone()
        assert row is not None
        return row
    finally:
        database.close()


def _publication_manifest_count(settings: CoreSettings) -> int:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                "SELECT count(*) AS count FROM publication.manifests"
            ).fetchone()
        assert row is not None
        return int(row["count"])
    finally:
        database.close()
