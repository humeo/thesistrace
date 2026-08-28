from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.authentication import InvalidLoginSession
from thesistrace.entrypoints.http import create_app
from thesistrace.entrypoints.runtime import CoreSettings
from thesistrace.entrypoints.schema import CORE_SCHEMAS, initialize_core
from thesistrace.researcher import ResearcherIdentity

PUBLIC_ORIGIN = "https://ownership.test"
RESEARCHER_A = ResearcherIdentity(
    researcher_id=UUID("40000000-0000-4000-8000-000000000004"),
    email="http-owner-a@example.test",
    display_label="HTTP Owner A",
)
RESEARCHER_B = ResearcherIdentity(
    researcher_id=UUID("50000000-0000-4000-8000-000000000005"),
    email="http-owner-b@example.test",
    display_label="HTTP Owner B",
)


class CookieIdentityVerifier:
    async def verify(self, cookie: str | None) -> ResearcherIdentity:
        identities = {
            "session=owner-a": RESEARCHER_A,
            "session=owner-b": RESEARCHER_B,
        }
        try:
            return identities[cookie]
        except KeyError as error:
            raise InvalidLoginSession from error


def test_two_researchers_have_http_success_and_known_id_non_enumeration() -> None:
    settings = CoreSettings.from_environment()
    _drop_core_schemas(settings.database_url)
    initialize_core(settings.database_url)
    app = create_app(
        settings,
        auth_verifier=CookieIdentityVerifier(),
        public_origin=PUBLIC_ORIGIN,
    )
    headers_a = {"cookie": "session=owner-a", "origin": PUBLIC_ORIGIN}
    headers_b = {"cookie": "session=owner-b", "origin": PUBLIC_ORIGIN}

    with TestClient(app) as client:
        for headers, identity in (
            (headers_a, RESEARCHER_A),
            (headers_b, RESEARCHER_B),
        ):
            bootstrap = client.post("/api/researcher/bootstrap", headers=headers)
            assert bootstrap.status_code == 200
            assert bootstrap.json()["researcher_id"] == str(identity.researcher_id)

        folder = client.post(
            "/api/research-folders",
            headers=headers_a,
            json={"name": "Owner A Folder"},
        )
        assert folder.status_code == 201
        assert client.get(
            "/api/research-folders",
            headers={"cookie": "session=owner-a"},
        ).status_code == 200
        assert client.patch(
            f"/api/research-folders/{folder.json()['id']}",
            headers=headers_b,
            json={"name": "Owner B Cannot See This"},
        ).status_code == 404

        _insert_owned_http_fixtures(settings.database_url)

        run_a = client.get(
            "/api/research-runs/run-http-a",
            headers={"cookie": "session=owner-a"},
        )
        assert run_a.status_code == 200
        assert client.get(
            "/api/research-runs/run-http-a",
            headers={"cookie": "session=owner-b"},
        ).status_code == 404
        first_page = client.get(
            "/api/research-runs",
            headers={"cookie": "session=owner-a"},
            params={"limit": 1},
        )
        assert first_page.status_code == 200
        assert first_page.json()["next_cursor"] is not None
        assert client.get(
            "/api/research-runs",
            headers={"cookie": "session=owner-b"},
            params={"cursor": first_page.json()["next_cursor"]},
        ).status_code == 400

        batch_a = client.get(
            "/api/research-batches/batch-http-a",
            headers={"cookie": "session=owner-a"},
        )
        assert batch_a.status_code == 200
        assert "data_generation_id" not in batch_a.json()["scope"]
        assert client.get(
            "/api/research-batches/batch-http-a",
            headers={"cookie": "session=owner-b"},
        ).status_code == 404

        tracks_a = client.get(
            "/api/daily-tracks",
            headers={"cookie": "session=owner-a"},
        )
        assert tracks_a.status_code == 200
        assert [item["id"] for item in tracks_a.json()["items"]] == ["track-http-a"]
        assert client.get(
            "/api/daily-tracks/track-http-a",
            headers={"cookie": "session=owner-b"},
        ).status_code == 404


def _insert_owned_http_fixtures(database_url: str) -> None:
    database = PostgresDatabase(database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            for run_id in ("run-http-a", "run-http-a-second"):
                transaction.execute(
                    """
                    INSERT INTO research_runs.run_ownership (researcher_id, run_id)
                    VALUES (%s, %s)
                    """,
                    (RESEARCHER_A.researcher_id, run_id),
                )
                transaction.execute(
                    """
                    INSERT INTO research_runs.runs (
                        researcher_id, id, folder_id, name,
                        requested_start_date, requested_end_date,
                        status, immutable_input
                    ) VALUES (
                        %s, %s, 'folder_default', %s,
                        DATE '2026-08-01', DATE '2026-08-02',
                        'queued', %s
                    )
                    """,
                    (
                        RESEARCHER_A.researcher_id,
                        run_id,
                        run_id,
                        Jsonb(_immutable_run_input()),
                    ),
                )
                transaction.execute(
                    """
                    INSERT INTO research_runs.progress (
                        run_id, phase,
                        completed_warmup_sessions, total_warmup_sessions,
                        completed_research_sessions, total_research_sessions,
                        committed_chunk_count
                    ) VALUES (%s, 'queued', 0, 0, 0, 0, 0)
                    """,
                    (run_id,),
                )
            scope = {
                "start_date": "2026-08-01",
                "end_date": "2026-08-02",
                "universe": "top300",
                "neutralization": "none",
                "numeric_execution_contract": "numeric-v1",
                "semantic_versions": {},
                "data_generation_id": "private-generation-manifest",
                "data_through_session": "2026-08-02",
            }
            transaction.execute(
                """
                INSERT INTO research_batches.batches (
                    researcher_id, id, batch_kind, status, scope
                ) VALUES (%s, 'batch-http-a', 'factor_evaluation', 'queued', %s)
                """,
                (RESEARCHER_A.researcher_id, Jsonb(scope)),
            )
            transaction.execute(
                """
                INSERT INTO research_batches.items (
                    researcher_id, batch_id, ordinal, item_key,
                    research_run_id, dependency_role
                ) VALUES (%s, 'batch-http-a', 1, 'factor',
                          'run-http-a', 'factor')
                """,
                (RESEARCHER_A.researcher_id,),
            )
            transaction.execute(
                """
                INSERT INTO research_batches.progress (
                    batch_id, completed_items, total_items
                ) VALUES ('batch-http-a', 0, 1)
                """
            )
            origin = _tracking_origin("run-http-a")
            transaction.execute(
                """
                INSERT INTO daily_tracks.tracks (
                    researcher_id, id, status, seed_run_id, origin
                ) VALUES (%s, 'track-http-a', 'active', 'run-http-a', %s)
                """,
                (RESEARCHER_A.researcher_id, Jsonb(origin)),
            )
            transaction.execute(
                """
                INSERT INTO daily_tracks.session_checkpoints (
                    manifest_sha256, track_id, boundary_session,
                    terminal_strategy_state, data_generation_id, provenance
                ) VALUES (%s, 'track-http-a', DATE '2026-08-02',
                          '{}'::jsonb, 'generation', '{}'::jsonb)
                """,
                ("c" * 64,),
            )
            transaction.execute(
                """
                INSERT INTO daily_tracks.session_tracking_states (
                    track_id, origin_session, origin_checkpoint_manifest_sha256,
                    current_checkpoint_manifest_sha256
                ) VALUES ('track-http-a', DATE '2026-08-02', %s, %s)
                """,
                ("c" * 64, "c" * 64),
            )
    finally:
        database.close()


def _tracking_origin(run_id: str) -> dict[str, object]:
    return {
        "seed_run_id": run_id,
        "immutable_input": {},
        "seed_data_generation_id": "generation",
        "seed_data_through_session": "2026-08-02",
        "verified_result": {
            "kind": "research.result",
            "research_run_id": run_id,
            "schema_version": "research-result-v1",
            "result_manifest_sha256": "d" * 64,
            "result_checksum_sha256": "e" * 64,
        },
        "initial_strategy_state": {
            "session": "2026-08-02",
            "gross_cash": "1",
            "net_cash": "1",
            "gross_nav": "1",
            "net_nav": "1",
            "benchmark_nav": "1",
            "cumulative_transaction_cost": "0",
            "positions": [],
            "rebalance_phase": {},
            "pending_signal": None,
            "last_daily_observation": {},
            "metric_state": {},
        },
        "calculation_contracts": {},
    }


def _immutable_run_input() -> dict[str, object]:
    return {
        "formula_source": "close",
        "alpha_expression": {"kind": "field", "field_id": "price.close.adjusted"},
        "hypothesis": None,
        "requested_start_date": "2026-08-01",
        "requested_end_date": "2026-08-02",
        "field_bindings": {"price.close.adjusted": "close"},
        "universe": "top300",
        "neutralization": "none",
        "research_kind": "factor_evaluation",
        "numeric_execution_contract": "thesistrace-numeric-v1",
        "semantic_versions": {"factor": "factor-v1", "kernel": "kernel-v4"},
        "alpha_admission": {
            "effective_lookback": 0,
            "node_count": 1,
            "depth": 1,
            "formula_work": 1,
            "estimated_run_work": 2,
        },
        "data_admission": {
            "generation_manifest_sha256": "a" * 64,
            "data_through_session": "2026-08-02",
            "coverage_start": "2026-08-01",
            "coverage_end": "2026-08-02",
            "first_research_session": "2026-08-01",
            "last_research_session": "2026-08-02",
            "calculation_session_count": 2,
            "universe_instrument_count": 1,
            "financial_research_readiness": "not_ready",
        },
        "execution_plan": {
            "execution_memory_bytes": 1,
            "chunk_time_target_seconds": 30,
            "chunk_session_count": 2,
            "time_target_exceeded": False,
            "estimated_peak_bytes": 1,
            "estimated_chunk_work": 2,
            "maximum_universe_cardinality": 1,
            "calculation_sessions": ["2026-08-01", "2026-08-02"],
            "research_session_offset": 0,
            "research_session_count": 2,
            "chunks": [
                {
                    "ordinal": 1,
                    "first_session": "2026-08-01",
                    "last_session": "2026-08-02",
                    "session_count": 2,
                    "warmup_session_count": 0,
                    "research_session_count": 2,
                }
            ],
        },
    }


def _drop_core_schemas(database_url: str) -> None:
    database = PostgresDatabase(database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            for schema in reversed((*CORE_SCHEMAS, "thesistrace_meta")):
                transaction.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    finally:
        database.close()
