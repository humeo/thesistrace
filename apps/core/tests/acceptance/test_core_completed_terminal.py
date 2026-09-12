from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from core_runtime import TEST_RESEARCHER, drop_product_schemas
from core_runtime import create_initialized_test_app as create_app
from fastapi.testclient import TestClient
from test_core_daily_track_detail import (
    _business_sessions,
    _publish_head,
    _refresh_daily_track,
    _run_command,
    _run_worker_once,
)

from thesistrace.benchmark import BenchmarkLevel, BenchmarkSnapshotStore
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.schema import initialize_core


@pytest.mark.skipif(not core_environment_is_configured(), reason="isolated runtime required")
@pytest.mark.parametrize(
    "formula,exposure,terminal_nav",
    [
        ("close", "1", "99969.31"),
        ("if_else(close > 0 and not (close == 0), close, -close)", "7 / 10", "99978.3"),
        ("close", "0", "100000"),
    ]
)
def test_fixed_exposure_publishes_and_tracks_its_first_entry(
    tmp_path: Path, formula, exposure, terminal_nav,
):
    settings = replace(
        CoreSettings.from_environment(),
        data_mount=tmp_path / "data",
        benchmark_mount=tmp_path / "benchmark",
    )
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    sessions = _business_sessions(date(2024, 8, 1), count=3)
    BenchmarkSnapshotStore(settings.benchmark_mount).publish(
        (
            BenchmarkLevel("2010-01-04", "3500"),
            *(BenchmarkLevel(session, "4000") for session in sessions),
        ),
        published_at=datetime(2026, 8, 10, 8, tzinfo=UTC),
    )
    _publish_head(settings, sessions=sessions, expected_manifest=None, operation_id="one-day")
    with TestClient(create_app(settings)) as client:
        command = {
            **_run_command("one-day", start_date=sessions[0], end_date=sessions[0]),
            "initial_cash_cny": "100000", "formula": formula, "exposure_expression": exposure,
            "selection_every_sessions": 5,
        }
        spec = {
            key: value for key, value in command.items()
            if key not in {"request_id", "folder_id", "name"}
        }
        runtime = client.app.state.core_runtime

        def persistent_counts():
            with runtime.database.transaction() as transaction:
                return transaction.execute(
                    "SELECT (SELECT count(*) FROM research_runs.runs) AS runs, "
                    "(SELECT count(*) FROM data.generation_pins) AS pins"
                ).fetchone()

        before = persistent_counts()
        diagnosis = client.post("/api/research/diagnostics", json=spec)
        assert diagnosis.status_code == 200, diagnosis.text
        assert diagnosis.json() == {"valid": True, "issues": []}
        rejected = client.post(
            "/api/research/diagnostics", json={**spec, "exposure_expression": "1.1"},
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["valid"] is False
        assert rejected.json()["issues"][0]["field"] == "exposure_expression"
        assert persistent_counts() == before
        if exposure == "7 / 10":
            import anyio
            from test_core_research_agent_mcp_runs import _mcp_client

            async def native_diagnosis():
                async with _mcp_client(settings, tmp_path / "exposure-mcp.stderr.log") as agent:
                    result = await agent.call_tool("diagnose_research_spec", {"spec": spec})
                    assert result.is_error is False, result
                    assert result.structured_content == {"valid": True, "issues": []}
                    local = await agent.call_tool("diagnose_alpha_formula", {
                        "source": exposure, "context": "exposure",
                    })
                    assert local.is_error is False, local
                    assert local.structured_content["valid"] is True

            anyio.run(native_diagnosis)
            assert persistent_counts() == before
        accepted = client.post("/api/research-runs", json=command)
        assert accepted.status_code == 202, accepted.text
        run_id = accepted.json()["id"]
        worker = _run_worker_once(settings, "research")
        assert worker.returncode == 0, worker.stdout + worker.stderr
        detail = client.get(f"/api/research-runs/{run_id}").json()
        assert detail["status"] == "succeeded", detail
        assert detail["input"]["selection_every_sessions"] == 5
        assert detail["input"]["exposure_expression"] == exposure
        result = detail["result"]
        account = result["terminal_strategy_state"]
        assert account["target_exposure"] == (0.7 if exposure == "7 / 10" else float(exposure))
        assert account["pending_target"]["exposure"] == account["target_exposure"]
        assert account["target_selection"]["selected_instrument_ids"]
        assert account["positions"] == []
        assert Decimal(account["net_nav"]) == Decimal("100000")
        assert account["pending_target"]["signal_session"] == sessions[0]
        assert result["strategy"]["summary"]["entry_session"] is None
        assert result["strategy"]["comparison"] == {
            "status": "unavailable",
            "reason": "no_entry_open",
        }
        started = client.post(
            f"/api/research-runs/{run_id}/daily-tracks", json={"request_id": "one-day-track"}
        )
        assert started.status_code == 201, started.text
        track_id = started.json()["id"]
        seed = client.get(f"/api/daily-tracks/{track_id}")
        assert seed.status_code == 200, seed.text
        assert seed.json()["strategy"]["comparison"]["reason"] == "no_entry_open"
        _refresh_daily_track(client, track_id, "first-entry")
        worker = _run_worker_once(settings, "tracking")
        assert worker.returncode == 0, worker.stdout + worker.stderr
        tracked = client.get(f"/api/daily-tracks/{track_id}").json()
        assert tracked["strategy_session"] == sessions[-1], tracked
        assert tracked["strategy"]["comparison"]["status"] == "available"
        assert tracked["strategy"]["comparison"]["entry"]["session"] == sessions[1]
        if exposure == "0":
            assert tracked["observation"]["holdings"] == []
            metrics = tracked["strategy"]["comparison"]["metrics"]
            assert metrics["net_strategy_cumulative_return"] == 0
            assert metrics["benchmark_cumulative_return"] == 0
        assert Decimal(tracked["strategy"]["observations"][-1]["net_nav"]) == Decimal(terminal_nav)


@pytest.mark.skipif(not core_environment_is_configured(), reason="isolated runtime required")
@pytest.mark.parametrize(
    "formula, identifiers",
    [
        ("close * universe_advancing_fraction()", ("universe_advancing_fraction",)),
        (
            "close * (1 + universe_advancing_fraction() + universe_return())",
            ("universe_advancing_fraction", "universe_return"),
        ),
        (
            "close * (1 + industry_return(801010) + industry_advancing_fraction(801010))",
            ("industry_advancing_fraction", "industry_return"),
        ),
    ],
)
def test_common_statistics_publish_from_checkpoint_to_completed_result(
    tmp_path: Path,
    formula,
    identifiers,
    monkeypatch,
):
    import test_core_daily_track_detail as fixture_module
    from test_core_current_head_research_run_execution import _stored_execution

    from thesistrace.publication import PublishedRef
    from thesistrace.research_run.result import read_result_bundle

    is_industry = identifiers[0].startswith("industry_")
    if is_industry:
        original_canonical = fixture_module._canonical

        def industry_canonical(sessions):
            canonical = original_canonical(sessions)
            for membership in canonical["industry_membership"]:
                membership["sw2021_l1"] = "801010"
            return canonical

        monkeypatch.setattr(fixture_module, "_canonical", industry_canonical)

    settings = replace(
        CoreSettings.from_environment(),
        data_mount=tmp_path / "data",
        benchmark_mount=tmp_path / "benchmark",
    )
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    sessions = _business_sessions(date(2024, 8, 1), count=5)
    BenchmarkSnapshotStore(settings.benchmark_mount).publish(
        (BenchmarkLevel("2010-01-04", "3500"), *(BenchmarkLevel(day, "4000") for day in sessions)),
        published_at=datetime(2026, 8, 10, 8, tzinfo=UTC),
    )
    generation = _publish_head(
        settings, sessions=sessions, expected_manifest=None, operation_id="common"
    )
    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/research-runs",
            json={
                **_run_command("common-result", start_date=sessions[1], end_date=sessions[3]),
                "initial_cash_cny": "100000",
                "formula": formula,
            },
        )
        assert accepted.status_code == 202, accepted.text
        run_id = accepted.json()["id"]
        if is_industry:
            from test_core_current_head_research_run_retry import (
                _install_transient_result_publication_failure,
                _remove_transient_result_publication_failure,
            )

            _install_transient_result_publication_failure(settings)
            try:
                worker = _run_worker_once(settings, "research")
                assert worker.returncode == 0, worker.stdout + worker.stderr
            finally:
                _remove_transient_result_publication_failure(settings)
            assert client.get(f"/api/research-runs/{run_id}").json()["status"] == "running"
            events = []
            assert (
                client.app.state.core_runtime.research_runs.process_next(
                    on_execution_event=events.append,
                )
                is True
            )
            assert any(event.get("resumed_from_checkpoint") is True for event in events)
            assert any(event.get("reused_checkpoint") is True for event in events)
        else:
            worker = _run_worker_once(settings, "research")
            assert worker.returncode == 0, worker.stdout + worker.stderr
        stored = _stored_execution(settings, run_id)
        assert stored["status"] == "succeeded", stored
        assert stored["attempt_data_generation_id"] == generation
        bundle = client.app.state.core_runtime.publication.read(
            PublishedRef(
                manifest_sha256=stored["result_manifest_sha256"],
                kind="research.result",
                provenance=stored["result_provenance"],
            )
        )
        values = read_result_bundle(bundle, research_kind="strategy_backtest")[
            "common_input_observations"
        ]
        assert [row["session"] for row in values] == [
            day for day in sessions[1:4] for _ in identifiers
        ]
        assert {row["identifier"] for row in values} == set(identifiers)
        assert all(row["valid_count"] == row["member_count"] > 0 for row in values)
        assert all(row["exclusions"] == {} for row in values)

        from thesistrace.research_run.models import CommonInputObservationsResultSectionInput

        collected = []
        cursor = None
        for _ in range(len(values)):
            page = client.app.state.core_runtime.research_runs.get_result_section(
                TEST_RESEARCHER.researcher_id,
                CommonInputObservationsResultSectionInput(
                    run_id=run_id,
                    section="common_input_observations",
                    cursor=cursor,
                    limit=1,
                ),
            )
            assert page is not None
            assert page.research_kind == "strategy_backtest"
            collected.extend(item.model_dump(mode="json") for item in page.items)
            cursor = page.next_cursor
        assert cursor is None
        assert collected == values

        from thesistrace.daily_track.service import _read_publication_json

        started = client.post(
            f"/api/research-runs/{run_id}/daily-tracks",
            json={"request_id": "common-track"},
        )
        assert started.status_code == 201, started.text
        track_id = started.json()["id"]
        _refresh_daily_track(client, track_id, "common-track-refresh")
        worker = _run_worker_once(settings, "tracking")
        assert worker.returncode == 0, worker.stdout + worker.stderr
        tracked = client.get(f"/api/daily-tracks/{track_id}").json()
        assert tracked["strategy_session"] == sessions[-1], tracked
        runtime = client.app.state.core_runtime
        with runtime.database.transaction() as transaction:
            latest = transaction.execute(
                "SELECT manifest_sha256, provenance FROM daily_tracks.session_checkpoints "
                "WHERE track_id = %s ORDER BY boundary_session DESC LIMIT 1",
                (track_id,),
            ).fetchone()
        checkpoint = _read_publication_json(
            runtime.publication,
            PublishedRef(
                manifest_sha256=latest["manifest_sha256"],
                kind="daily-track.checkpoint",
                provenance=latest["provenance"],
            ),
            payload_name="checkpoint",
        )
        common = checkpoint["common_input_observations"]
        assert [item["session"] for item in common] == [sessions[-1]] * len(identifiers)
        assert {item["identifier"] for item in common} == set(identifiers)
        assert common[0]["valid_count"] == common[0]["member_count"] > 0

        from thesistrace.daily_track.models import (
            DailyTrackCommonInputObservationsResultSectionInput,
        )

        cursor = None
        track_values = []
        for _ in range(len(values) + len(common)):
            page = runtime.daily_tracks.get_result_section(
                TEST_RESEARCHER.researcher_id,
                DailyTrackCommonInputObservationsResultSectionInput(
                    track_id=track_id,
                    section="common_input_observations",
                    cursor=cursor,
                    limit=1,
                ),
            )
            assert page is not None
            track_values.extend(item.model_dump(mode="json") for item in page.items)
            cursor = page.next_cursor
        assert cursor is None
        assert track_values == values + common

        for path, expected in (
            (f"/api/research-runs/{run_id}/common-input-observations", values),
            (f"/api/daily-tracks/{track_id}/common-input-observations", values + common),
        ):
            http_page = client.get(path, params={"limit": 1})
            assert http_page.status_code == 200, http_page.text
            assert http_page.json()["items"] == expected[:1]
            assert client.get(path, params={"cursor": "invalid"}).status_code == 400
            assert client.get(path, params={"limit": 51}).status_code == 422

        import anyio
        from test_core_research_agent_mcp_runs import _mcp_client

        async def read_native_common_results():
            async with _mcp_client(settings, tmp_path / "common-results-mcp.stderr.log") as agent:
                for tool, identity, expected in (
                    ("get_research_run_result", {"run_id": run_id}, values),
                    ("get_daily_track_result", {"track_id": track_id}, values + common),
                ):
                    received = []
                    cursor = None
                    for _ in range(len(expected)):
                        response = await agent.call_tool(
                            tool,
                            {
                                **identity,
                                "section": "common_input_observations",
                                "limit": 1,
                                "cursor": cursor,
                            },
                        )
                        assert response.is_error is False, response
                        page = response.structured_content
                        assert page["section"] == "common_input_observations"
                        assert len(page["items"]) == 1
                        received.extend(page["items"])
                        cursor = page["next_cursor"]
                    assert cursor is None
                    assert received == expected

        anyio.run(read_native_common_results)
