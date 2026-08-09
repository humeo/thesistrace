from __future__ import annotations

from collections.abc import Mapping

import pytest
from core_runtime import create_migrated_test_app as create_app
from fastapi.testclient import TestClient
from fixture_release import publish_fixture_release

from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.publication import PublicationVerificationError


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_succeeded_run_detail_shows_bounded_result_and_reopens_after_restart() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        run_id = _execute_run(client, request_id="ticket-21-result")
        response = client.get(f"/api/research-runs/{run_id}")

        assert response.status_code == 200
        detail = response.json()
        assert set(detail) == {
            "id",
            "status",
            "definition_id",
            "definition_revision",
            "dataset_release_id",
            "result",
        }
        assert detail["status"] == "succeeded"
        result = detail["result"]
        assert set(result) == {"factor", "strategy", "provenance"}

        horizons = result["factor"]["horizons"]
        assert set(horizons) == {"1", "5", "20"}
        for expected_horizon in (1, 5, 20):
            horizon = horizons[str(expected_horizon)]
            assert set(horizon) == {"horizon", "summary", "coverage"}
            assert horizon["horizon"] == expected_horizon
            assert set(horizon["summary"]) == {
                "ic",
                "rank_ic",
                "quantile_returns",
                "top_bottom_return",
            }
            assert set(horizon["coverage"]) == {
                "signal_session_count",
                "ic_valid_session_count",
                "rank_ic_valid_session_count",
                "quantile_valid_session_count",
            }
            assert horizon["coverage"]["signal_session_count"] == 504
            assert horizon["coverage"]["ic_valid_session_count"] == horizon[
                "summary"
            ]["ic"]["valid_session_count"]
            assert horizon["coverage"]["rank_ic_valid_session_count"] == horizon[
                "summary"
            ]["rank_ic"]["valid_session_count"]
            assert all(
                not isinstance(value, list)
                for value in horizon["summary"]["quantile_returns"].values()
            )
            assert not isinstance(horizon["summary"]["top_bottom_return"], list)

        strategy = result["strategy"]
        assert set(strategy) == {"summary", "benchmark", "observations"}
        assert strategy["benchmark"] == {
            "universe": "top1000",
            "methodology": "selected_universe_equal_weight",
        }
        assert len(strategy["observations"]) == 504
        assert all(
            set(observation)
            == {
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
            for observation in strategy["observations"]
        )
        assert result["provenance"]["research_run_id"] == run_id
        assert result["provenance"]["dataset_release_id"] == detail[
            "dataset_release_id"
        ]
        assert set(result["provenance"]) == {
            "schema_version",
            "research_run_id",
            "immutable_input_sha256",
            "dataset_release_id",
            "calculation_contracts",
            "semantic_versions",
        }

        serialized = str(result).lower()
        for excluded in (
            "alpha_matrix",
            "alpha_values",
            "forward_labels",
            "daily_factor_observations",
            "orders",
            "fills",
            "terminal_strategy_state",
            "positions",
            "attempt",
            "manifest",
            "object_key",
            "continuation",
            "result_url",
            "download",
        ):
            assert excluded not in serialized
        assert client.get(f"/api/research-runs/{run_id}/result").status_code == 404
        assert _result_bundle_bytes(client, run_id) <= 1_048_576

    with TestClient(create_app(settings)) as restarted:
        reopened = restarted.get(f"/api/research-runs/{run_id}")
        assert reopened.status_code == 200
        assert reopened.json() == detail


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_result_read_failure_returns_only_a_sanitized_product_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        run_id = _execute_run(client, request_id="ticket-21-read-failure")
        runtime = client.app.state.core_runtime

        def fail_read(_published_ref: object) -> object:
            raise PublicationVerificationError(
                "private bucket object checksum mismatch at secret/object/key"
            )

        monkeypatch.setattr(runtime.publication, "read", fail_read)
        response = client.get(f"/api/research-runs/{run_id}")

        assert response.status_code == 503
        assert response.json() == {"detail": "ResearchRun Result unavailable"}
        assert "checksum" not in response.text.lower()
        assert "bucket" not in response.text.lower()
        assert "object" not in response.text.lower()


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_result_preserves_legal_null_factor_summary_fields() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        run_id = _execute_run(
            client,
            request_id="ticket-21-null-summary",
            alpha={
                "operator_id": "subtract",
                "operands": [
                    {"field_id": "price.close.adjusted"},
                    {"field_id": "price.close.adjusted"},
                ],
            },
        )
        response = client.get(f"/api/research-runs/{run_id}")

        assert response.status_code == 200
        horizons = response.json()["result"]["factor"]["horizons"]
        for horizon in horizons.values():
            assert horizon["summary"]["ic"] == {
                "mean": None,
                "sample_deviation": None,
                "icir": None,
                "positive_fraction": None,
                "valid_session_count": 0,
            }
            assert horizon["summary"]["rank_ic"] == {
                "mean": None,
                "sample_deviation": None,
                "icir": None,
                "positive_fraction": None,
                "valid_session_count": 0,
            }
            assert set(horizon["summary"]["quantile_returns"]) == {
                "q1",
                "q2",
                "q3",
                "q4",
                "q5",
            }
            assert horizon["summary"]["top_bottom_return"] is None


def _execute_run(
    client: TestClient,
    *,
    request_id: str,
    alpha: dict[str, object] | None = None,
) -> str:
    publish_fixture_release(client)
    runtime = client.app.state.core_runtime
    accepted = client.post(
        "/api/definitions/run",
        json={
            "request_id": request_id,
            "name": "Bounded visible result",
            "alpha": alpha
            or {
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
    assert runtime.research_runs.process_next() is True
    return str(run_id)


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


def _result_bundle_bytes(client: TestClient, run_id: str) -> int:
    database = client.app.state.core_runtime.database
    with database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT octet_length(manifest.manifest_bytes)
                   + coalesce(sum(object.byte_size), 0) AS exact_bytes
            FROM research_runs.runs AS run
            JOIN publication.manifests AS manifest
              ON manifest.sha256 = run.result_manifest_sha256
            LEFT JOIN publication.manifest_objects AS link
              ON link.manifest_sha256 = manifest.sha256
            LEFT JOIN publication.objects AS object
              ON object.sha256 = link.object_sha256
            WHERE run.id = %s
            GROUP BY manifest.manifest_bytes
            """,
            (run_id,),
        ).fetchone()
    assert isinstance(row, Mapping)
    return int(row["exact_bytes"])
