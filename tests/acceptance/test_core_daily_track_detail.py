from __future__ import annotations

import copy
import json
from collections.abc import Mapping

import pytest
from core_runtime import create_migrated_test_app as create_app
from fastapi.testclient import TestClient
from fixture_release import latest_fixture_release, publish_fixture_release

from thesistrace._postgres import PostgresDatabase
from thesistrace.adapters.fixture_data import FixtureDataSource, _append_session
from thesistrace.data.source import CanonicalSourceBatch, CollectionPlan, DataSource
from thesistrace.entrypoints.runtime import (
    CoreRuntime,
    CoreSettings,
    core_environment_is_configured,
)
from thesistrace.publication import PublishedRef
from thesistrace.research_kernel import (
    AdvanceInput,
    KernelState,
    RunInput,
    advance,
    continuation_snapshot,
    run,
)
from thesistrace.research_kernel.canonical_state import (
    canonical_sessions,
    slice_canonical_sessions,
)


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_daily_track_detail_keeps_recent_windows_and_origin_metrics() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        first_run = _admit_and_execute(client, request_id="ticket-32-first", universe="top1000")
        started = client.post(
            f"/api/research-runs/{first_run['id']}/daily-tracks",
            json={"request_id": "ticket-32-first-track"},
        )
        assert started.status_code == 201
        track = started.json()
        track_id = track["id"]

        seed_detail = client.get(f"/api/daily-tracks/{track_id}")
        assert seed_detail.status_code == 200
        assert seed_detail.json()["lag_releases"] == 0
        assert len(seed_detail.json()["strategy"]["observations"]) == 504

        first_wide_release = _publish_successor(
            client,
            request_id="ticket-32-first-wide-release",
            source=_WideFixtureDataSource(appended_session_count=300),
        )
        lagging = client.get(f"/api/daily-tracks/{track_id}").json()
        assert lagging["head_release_id"] == track["seed_release_id"]
        assert lagging["lag_releases"] == 1

        assert runtime.daily_tracks.process_next() is True
        wide_release = _publish_successor(
            client,
            request_id="ticket-32-second-wide-release",
            source=_WideFixtureDataSource(appended_session_count=205),
        )
        assert wide_release["predecessor_id"] == first_wide_release["id"]
        assert runtime.daily_tracks.process_next() is True
        detail = client.get(f"/api/daily-tracks/{track_id}").json()
        assert detail["status"] == "active"
        assert detail["head_release_id"] == wide_release["id"]
        assert detail["lag_releases"] == 0
        assert detail["blocked_reason"] is None
        assert detail["origin"] == {
            "seed_run_id": first_run["id"],
            "seed_release_id": track["seed_release_id"],
            "definition_id": first_run["definition_id"],
            "definition_revision": first_run["definition_revision"],
            "result_checksum_sha256": track["result_checksum_sha256"],
            "strategy_session": track["strategy_session"],
        }

        origin = _stored_origin(runtime.database, track_id)
        reference = _reference_track_state(
            runtime,
            origin=origin,
            release_ids=[first_wide_release["id"], wide_release["id"]],
        )
        reference_output = reference.output_snapshot()
        reference_factor = reference_output["factor_evaluation"]
        target_calendar = canonical_sessions(
            runtime.data.load_canonical(wide_release["id"]),
            "Head Dataset Release",
        )
        for horizon in ("1", "5", "20"):
            factor = detail["factor"]["horizons"][horizon]
            expected = reference_factor["horizons"][horizon]
            expected_daily = expected["daily"]
            expected_sessions = [item["session"] for item in expected_daily]
            assert expected_sessions == target_calendar[-504:]
            assert factor["horizon"] == int(horizon)
            assert factor["summary"] == expected["summary"]
            assert factor["coverage"] == {
                "signal_session_count": len(expected_daily),
                "ic_valid_session_count": expected["summary"]["ic"][
                    "valid_session_count"
                ],
                "rank_ic_valid_session_count": expected["summary"]["rank_ic"][
                    "valid_session_count"
                ],
                "quantile_valid_session_count": sum(
                    item["quantile_reason"] is None for item in expected_daily
                ),
            }

        retained = _recent_checkpoint_observations(runtime, track_id)
        observations = detail["strategy"]["observations"]
        assert len(retained) == 506
        assert len(observations) == 504
        assert observations == retained[-504:]
        assert observations[0]["session"] == retained[2]["session"]
        assert [item["session"] for item in observations] == sorted(
            item["session"] for item in observations
        )
        api_metrics = detail["strategy"]["summary"]["metrics"]
        reference_metrics = reference_output["strategy_backtest"]["metrics"]
        for metric in (
            "net_cumulative_return",
            "benchmark_cumulative_return",
            "annualized_excess_return",
            "sharpe",
        ):
            assert api_metrics[metric] == reference_metrics[metric]
        assert api_metrics["maximum_drawdown"]["value"] == reference_metrics[
            "maximum_drawdown"
        ]["value"]
        assert api_metrics["transaction_costs"]["cumulative_amount"] == reference_metrics[
            "transaction_costs"
        ]["cumulative_amount"]

        recent_canonical = slice_canonical_sessions(
            runtime.data.load_canonical(wide_release["id"]),
            target_calendar[-756:],
        )
        recent_only = run(_run_input(origin, recent_canonical)).artifacts_snapshot()[
            "strategy_backtest"
        ]
        assert api_metrics["net_cumulative_return"] != recent_only["metrics"][
            "net_cumulative_return"
        ]
        assert detail["strategy"]["benchmark"] == {
            "universe": "top1000",
            "methodology": "selected_universe_equal_weight",
        }

        second_run = _admit_and_execute(
            client,
            request_id="ticket-32-second",
            universe="top300",
        )
        second_started = client.post(
            f"/api/research-runs/{second_run['id']}/daily-tracks",
            json={"request_id": "ticket-32-second-track"},
        )
        assert second_started.status_code == 201
        isolated = client.get(f"/api/daily-tracks/{track_id}").json()
        assert isolated["strategy"]["benchmark"]["universe"] == "top1000"

        latest_release = _publish_successor(
            client,
            request_id="ticket-32-lag-release",
            source=_WideFixtureDataSource(appended_session_count=1),
        )
        before_restart = client.get(f"/api/daily-tracks/{track_id}").json()
        assert before_restart["head_release_id"] == wide_release["id"]
        assert before_restart["lag_releases"] == 1
        assert latest_release["id"] != wide_release["id"]

        serialized = json.dumps(before_restart, sort_keys=True).lower()
        for forbidden in (
            "checkpoint",
            "generation",
            "advance",
            "attempt",
            "manifest",
            "object_key",
            "continuation",
        ):
            assert forbidden not in serialized

    with TestClient(create_app(settings)) as restarted:
        reopened = restarted.get(f"/api/daily-tracks/{track_id}")
        assert reopened.status_code == 200
        assert reopened.json() == before_restart


class _WideFixtureDataSource:
    def __init__(self, *, appended_session_count: int) -> None:
        self._appended_session_count = appended_session_count

    def collect(self, plan: CollectionPlan) -> CanonicalSourceBatch:
        if plan.kind == "bootstrap":
            return FixtureDataSource().collect(plan)
        if plan.previous_canonical is None or plan.after_session is None:
            raise AssertionError("incremental fixture requires predecessor canonical data")
        canonical = copy.deepcopy(dict(plan.previous_canonical))
        for _ in range(self._appended_session_count):
            _append_session(canonical)
        calendar = canonical["research_calendar"]
        assert isinstance(calendar, list)
        return CanonicalSourceBatch(
            source_name="fixture",
            collection_kind="incremental",
            source_lineage={
                "adapter": "ticket-32-wide-fixture",
                "after_session": plan.after_session,
                "appended_session_count": self._appended_session_count,
            },
            canonical=canonical,
            covered_session_range=(str(calendar[0]), str(calendar[-1])),
        )


def _admit_and_execute(
    client: TestClient,
    *,
    request_id: str,
    universe: str,
) -> dict[str, object]:
    runtime = client.app.state.core_runtime
    if latest_fixture_release(client) is None:
        publish_fixture_release(client)
    response = client.post(
        "/api/definitions/run",
        json={
            "request_id": request_id,
            "name": request_id,
            "alpha": {
                "operator_id": "ts_mean",
                "operands": [
                    {"field_id": "price.close.adjusted"},
                    {"literal": 20},
                ],
            },
            "universe": universe,
            "neutralization": "industry",
            "holdings_count": 30,
            "rebalance_every_sessions": 5,
        },
    )
    assert response.status_code == 200
    run = response.json()["run"]
    assert runtime.research_runs.process_next() is True
    completed = client.get(f"/api/research-runs/{run['id']}").json()
    assert completed["status"] == "succeeded"
    return completed


def _publish_successor(
    client: TestClient,
    *,
    request_id: str,
    source: DataSource,
) -> dict[str, object]:
    del request_id
    return publish_fixture_release(client, source=source)


def _recent_checkpoint_observations(
    runtime: CoreRuntime,
    track_id: str,
) -> list[dict[str, object]]:
    with runtime.database.transaction() as transaction:
        rows = transaction.execute(
            """
            SELECT manifest_sha256, provenance
            FROM daily_tracks.checkpoints
            WHERE track_id = %s
            ORDER BY strategy_session, target_release_id
            """,
            (track_id,),
        ).fetchall()
    by_session: dict[str, dict[str, object]] = {}
    for row in rows:
        bundle = runtime.publication.read(
            PublishedRef(
                manifest_sha256=str(row["manifest_sha256"]),
                kind="daily-track.checkpoint",
                provenance=dict(row["provenance"]),
            )
        )
        value = json.loads(bundle.payloads["checkpoint"].content)
        for observation in value["strategy_state"]["retained_delta"]:
            by_session[str(observation["session"])] = dict(observation)
    return [by_session[session] for session in sorted(by_session)]


def _stored_origin(database: PostgresDatabase, track_id: str) -> dict[str, object]:
    with database.transaction() as transaction:
        row = transaction.execute(
            "SELECT origin FROM daily_tracks.tracks WHERE id = %s",
            (track_id,),
        ).fetchone()
    assert row is not None
    return dict(row["origin"])


def _reference_track_state(
    runtime: CoreRuntime,
    *,
    origin: dict[str, object],
    release_ids: list[str],
) -> KernelState:
    seed = runtime.data.load_canonical(str(origin["seed_release_id"]))
    seed_sessions = canonical_sessions(seed, "Seed Dataset Release")
    state = run(
        _run_input(
            origin,
            slice_canonical_sessions(seed, seed_sessions[-756:]),
        )
    ).track_state
    for release_id in release_ids:
        target = runtime.data.load_canonical(release_id)
        prior_sessions = canonical_sessions(state.canonical_snapshot(), "Reference state")
        target_sessions = canonical_sessions(target, "Target Dataset Release")
        assert target_sessions[: len(prior_sessions)] == prior_sessions
        appended_sessions = target_sessions[len(prior_sessions) :]
        state = advance(
            AdvanceInput(
                prior_state=state,
                target_canonical_release=target,
                appended_sessions=appended_sessions,
                continuation=continuation_snapshot(state),
            )
        )
    return state


def _run_input(origin: dict[str, object], canonical: dict[str, object]) -> RunInput:
    immutable_input = origin["immutable_input"]
    assert isinstance(immutable_input, Mapping)
    definition = immutable_input["definition"]
    strategy = immutable_input["strategy"]
    costs = immutable_input["costs"]
    field_bindings = immutable_input["field_bindings"]
    assert isinstance(definition, Mapping)
    assert isinstance(strategy, Mapping)
    assert isinstance(costs, Mapping)
    assert isinstance(field_bindings, Mapping)
    content = definition["content"]
    assert isinstance(content, Mapping)
    return RunInput(
        canonical_data=canonical,
        alpha_expression=content["alpha"],
        field_bindings={str(key): str(value) for key, value in field_bindings.items()},
        universe=str(content["universe"]),
        neutralization=str(content["neutralization"]),
        holdings_count=int(strategy["holdings_count"]),
        rebalance_interval=int(strategy["rebalance_every_sessions"]),
        initial_cash_cny=str(strategy["initial_cash_cny"]),
        commission_rate_all_in=str(costs["commission_rate_all_in"]),
        commission_min_cny=str(costs["commission_min_cny"]),
        stamp_duty_sell_rate=str(costs["stamp_duty_sell_rate"]),
        transfer_fee_rate=str(costs["transfer_fee_rate"]),
    )


def _drop_product_schemas(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute("DROP SCHEMA IF EXISTS daily_tracks CASCADE")
            transaction.execute("DROP SCHEMA IF EXISTS research_runs CASCADE")
            transaction.execute("DROP SCHEMA IF EXISTS definitions CASCADE")
            transaction.execute("DROP SCHEMA IF EXISTS data CASCADE")
            transaction.execute("DROP SCHEMA IF EXISTS publication CASCADE")
    finally:
        database.close()
