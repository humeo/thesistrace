from __future__ import annotations

import pytest
from research_agent_trajectory import (
    MAX_FAILURE_DIAGNOSTIC_BYTES,
    AuthorizationExpired,
    CallTool,
    ConnectionDropped,
    DeterministicTrajectoryHarness,
    Finish,
    RediscoverTools,
    RefreshAuthorization,
    ScriptedExchange,
    ScriptedFakeModel,
    ScriptedPublicMCP,
    TrajectoryFailure,
    WaitForRetry,
    public_tools,
)
from research_agent_trajectory_fixtures import (
    alpha_catalog_payload,
    batch_polling_payload,
    daily_track_history_payload,
    daily_track_payload,
    discover_public_tools,
    factor_batch_command,
    factor_command,
    factor_result_payload,
    formula_diagnostics_payload,
    research_context_payload,
    run_polling_payload,
    trajectory_registry,
)

from thesistrace.research_agent.models import ResearchAgentScope

SAFE_SCOPES = frozenset(
    {
        ResearchAgentScope.RESEARCH_READ,
        ResearchAgentScope.RESEARCH_EXECUTE,
        ResearchAgentScope.TRACKING_READ,
        ResearchAgentScope.TRACKING_EXECUTE,
    }
)


def _discovered_tools(scopes: frozenset[ResearchAgentScope]):
    return public_tools(discover_public_tools(trajectory_registry(scopes)))


def _strategy_command(request_id: str) -> dict[str, object]:
    return {
        **factor_command(request_id),
        "name": "Strategy Test",
        "research_kind": "strategy_backtest",
        "holdings_count": 10,
        "rebalance_every_sessions": 5,
    }
def _tool_error(
    *,
    code: str,
    tool_name: str,
    retry_after_seconds: int | None = None,
    trace_id: str,
) -> dict[str, object]:
    return {
        "code": code,
        "message": "Tool request could not be completed",
        "retryable": code == "TEMPORARILY_UNAVAILABLE",
        "trace_id": trace_id,
        "retry_after_seconds": retry_after_seconds,
        "context": {
            "tool_name": tool_name,
            "run_id": None,
            "batch_id": None,
            "track_id": None,
            "request_id": None,
        },
    }


def test_fake_model_authors_submits_polls_and_pages_research_results() -> None:
    tools = _discovered_tools(SAFE_SCOPES)
    factor_command_payload = factor_command("request_factor_001")
    strategy_command = _strategy_command("request_strategy_001")
    factor_result = factor_result_payload("run_factor")
    observation_page_1 = {
        "section": "strategy_observations",
        "run_id": "run_strategy",
        "research_kind": "strategy_backtest",
        "items": [],
        "next_cursor": "strategy_page_2",
    }
    observation_page_2 = {**observation_page_1, "next_cursor": None}
    exchanges = [
        ScriptedExchange(
            "get_research_context", {}, research_context_payload()
        ),
        ScriptedExchange(
            "get_alpha_catalog",
            {"identifiers": ["close", "ts_mean"]},
            alpha_catalog_payload(),
        ),
        ScriptedExchange(
            "diagnose_alpha_formula",
            {"source": "unknown_alpha + close"},
            formula_diagnostics_payload("unknown_alpha + close"),
        ),
        ScriptedExchange(
            "diagnose_alpha_formula",
            {"source": "close"},
            formula_diagnostics_payload("close"),
        ),
        ScriptedExchange(
            "submit_research_run",
            factor_command_payload,
            {
                "outcome": "accepted",
                "run_id": "run_factor",
                "status": "queued",
                "replayed": False,
                "retry_after_seconds": 2,
            },
        ),
        ScriptedExchange(
            "get_research_run",
            {"run_id": "run_factor"},
            run_polling_payload(
                run_id="run_factor", research_kind="factor_evaluation", status="queued"
            ),
        ),
        ScriptedExchange(
            "get_research_run",
            {"run_id": "run_factor"},
            run_polling_payload(
                run_id="run_factor", research_kind="factor_evaluation", status="running"
            ),
        ),
        ScriptedExchange(
            "get_research_run",
            {"run_id": "run_factor"},
            run_polling_payload(
                run_id="run_factor", research_kind="factor_evaluation", status="succeeded"
            ),
        ),
        ScriptedExchange(
            "get_research_run_result",
            {"run_id": "run_factor", "section": "factor"},
            factor_result,
        ),
        ScriptedExchange(
            "submit_research_run",
            strategy_command,
            {
                "outcome": "accepted",
                "run_id": "run_strategy",
                "status": "queued",
                "replayed": False,
                "retry_after_seconds": 2,
            },
        ),
        ScriptedExchange(
            "get_research_run",
            {"run_id": "run_strategy"},
            run_polling_payload(
                run_id="run_strategy", research_kind="strategy_backtest", status="succeeded"
            ),
        ),
        ScriptedExchange(
            "get_research_run_result",
            {"run_id": "run_strategy", "section": "strategy_observations", "limit": 1},
            observation_page_1,
        ),
        ScriptedExchange(
            "get_research_run_result",
            {
                "run_id": "run_strategy",
                "section": "strategy_observations",
                "cursor": "strategy_page_2",
                "limit": 1,
            },
            observation_page_2,
        ),
    ]
    model = ScriptedFakeModel(
        [
            CallTool("get_research_context", {}),
            CallTool("get_alpha_catalog", {"identifiers": ["close", "ts_mean"]}),
            CallTool("diagnose_alpha_formula", {"source": "unknown_alpha + close"}),
            CallTool("diagnose_alpha_formula", {"source": "close"}),
            CallTool("submit_research_run", factor_command_payload),
            WaitForRetry(2),
            CallTool("get_research_run", {"run_id": "run_factor"}),
            WaitForRetry(2),
            CallTool("get_research_run", {"run_id": "run_factor"}),
            WaitForRetry(2),
            CallTool("get_research_run", {"run_id": "run_factor"}),
            CallTool("get_research_run_result", {"run_id": "run_factor", "section": "factor"}),
            CallTool("submit_research_run", strategy_command),
            WaitForRetry(2),
            CallTool("get_research_run", {"run_id": "run_strategy"}),
            CallTool(
                "get_research_run_result",
                {"run_id": "run_strategy", "section": "strategy_observations", "limit": 1},
            ),
            CallTool(
                "get_research_run_result",
                {
                    "run_id": "run_strategy",
                    "section": "strategy_observations",
                    "cursor": "strategy_page_2",
                    "limit": 1,
                },
            ),
            Finish(
                artifacts={
                    "run_ids": ["run_factor", "run_strategy"],
                    "result_sections": ["factor", "strategy_observations"],
                },
                product_state="research_results_ready",
            ),
        ]
    )

    result = DeterministicTrajectoryHarness(
        model=model,
        transport=ScriptedPublicMCP(
            tools_by_grant=[tools], exchanges=exchanges
        ),
        seed=41,
        fixed_uuid="00000000-0000-4000-8000-000000000041",
        max_steps=24,
        max_public_calls=16,
        max_poll_calls=4,
    ).run()

    assert result.product_state == "research_results_ready"
    assert result.artifacts["run_ids"] == ["run_factor", "run_strategy"]
    assert result.virtual_time_seconds == 8
    assert result.poll_counts == {"get_research_run": 4}
    assert result.public_call_count == 13
    assert result.estimated_cost_units == 13.25
    cursor_states = [
        item["next_cursor_present"]
        for item in result.trajectory
        if item.get("tool") == "get_research_run_result"
        and "next_cursor_present" in item
    ]
    assert cursor_states == [True, False]


def test_batch_trajectory_replays_admission_monitors_order_and_rejects_unsafe_cancel() -> None:
    tools = _discovered_tools(SAFE_SCOPES)
    command = factor_batch_command("request_batch_001")
    changed_command = {
        **command,
        "factors": [{**command["factors"][0], "formula": "open"}],
    }
    replayed = {
        "outcome": "accepted",
        "batch_id": "batch_test",
        "status": "queued",
        "replayed": True,
        "retry_after_seconds": 2,
    }
    conflict = _tool_error(
        code="IDEMPOTENCY_CONFLICT",
        tool_name="submit_research_batch",
        trace_id="trace_batch_conflict",
    )
    child_result = factor_result_payload("run_child_value")
    transport = ScriptedPublicMCP(
        tools_by_grant=[tools],
        exchanges=[
            ScriptedExchange(
                "submit_research_batch",
                command,
                ConnectionDropped("response lost after durable admission"),
            ),
            ScriptedExchange("submit_research_batch", command, replayed),
            ScriptedExchange("submit_research_batch", changed_command, conflict),
            ScriptedExchange(
                "get_research_batch",
                {"batch_id": "batch_test"},
                batch_polling_payload(status="queued"),
            ),
            ScriptedExchange(
                "get_research_batch",
                {"batch_id": "batch_test"},
                batch_polling_payload(status="succeeded"),
            ),
            ScriptedExchange(
                "get_research_run_result",
                {"run_id": "run_child_value", "section": "factor"},
                child_result,
            ),
        ],
    )
    result = DeterministicTrajectoryHarness(
        model=ScriptedFakeModel(
            [
                CallTool("submit_research_batch", command),
                CallTool("submit_research_batch", command),
                CallTool("submit_research_batch", changed_command),
                WaitForRetry(2),
                CallTool("get_research_batch", {"batch_id": "batch_test"}),
                WaitForRetry(2),
                CallTool("get_research_batch", {"batch_id": "batch_test"}),
                CallTool(
                    "get_research_run_result",
                    {"run_id": "run_child_value", "section": "factor"},
                ),
                CallTool(
                    "cancel_research_batch",
                    {"batch_id": "batch_test", "request_id": "cancel_not_granted"},
                ),
                Finish(
                    artifacts={
                        "batch_id": "batch_test",
                        "ordered_child_run_ids": [
                            "run_child_value",
                            "run_child_quality",
                        ],
                        "child_result_sections": ["factor"],
                    },
                    product_state="batch_succeeded",
                ),
            ]
        ),
        transport=transport,
        seed=42,
        fixed_uuid="00000000-0000-4000-8000-000000000042",
        max_steps=16,
        max_public_calls=8,
        max_poll_calls=2,
    ).run()

    assert result.product_state == "batch_succeeded"
    assert result.artifacts["ordered_child_run_ids"] == [
        "run_child_value",
        "run_child_quality",
    ]
    assert result.public_call_count == 6
    assert any(
        item.get("action") == "local_rejection"
        and item.get("tool") == "cancel_research_batch"
        for item in result.trajectory
    )
    assert any(item.get("replayed") is True for item in result.trajectory)
    assert any(item.get("code") == "IDEMPOTENCY_CONFLICT" for item in result.trajectory)


def test_authorized_batch_cancel_is_selected_through_public_contract() -> None:
    tools = _discovered_tools(frozenset(ResearchAgentScope))
    arguments = {"batch_id": "batch_test", "request_id": "cancel_batch_001"}
    outcome = {
        "outcome": "accepted",
        "batch_id": "batch_test",
        "status": "cancelled",
        "next_tool": "get_research_batch",
        "replayed": False,
        "retry_after_seconds": None,
    }
    result = DeterministicTrajectoryHarness(
        model=ScriptedFakeModel(
            [
                CallTool("cancel_research_batch", arguments),
                Finish(
                    artifacts={"batch_id": "batch_test"},
                    product_state="batch_cancelled",
                ),
            ]
        ),
        transport=ScriptedPublicMCP(
            tools_by_grant=[tools],
            exchanges=[ScriptedExchange("cancel_research_batch", arguments, outcome)],
        ),
        seed=43,
        fixed_uuid="00000000-0000-4000-8000-000000000043",
    ).run()

    assert result.product_state == "batch_cancelled"
    assert result.public_call_count == 1


def test_daily_track_trajectory_retries_only_blocked_state_and_pages_results() -> None:
    tools = _discovered_tools(SAFE_SCOPES)
    start = {"run_id": "run_strategy", "request_id": "start_track_001"}
    refresh = {"track_id": "track_test", "request_id": "refresh_track_001"}
    retry = {"track_id": "track_test", "request_id": "retry_track_001"}
    observation_page_1 = {
        "section": "strategy_observations",
        "track_id": "track_test",
        "items": [],
        "next_cursor": "track_page_2",
    }
    observation_page_2 = {**observation_page_1, "next_cursor": None}
    history = daily_track_history_payload()
    transport = ScriptedPublicMCP(
        tools_by_grant=[tools],
        exchanges=[
            ScriptedExchange(
                "start_daily_track",
                start,
                {
                    "outcome": "accepted",
                    "track_id": "track_test",
                    "status": "active",
                    "replayed": False,
                    "retry_after_seconds": 30,
                },
            ),
            ScriptedExchange("list_daily_tracks", {"limit": 20}, history),
            ScriptedExchange(
                "get_daily_track", {"track_id": "track_test"}, daily_track_payload(lagging=True)
            ),
            ScriptedExchange(
                "refresh_daily_track",
                refresh,
                {
                    "outcome": "accepted",
                    "track_id": "track_test",
                    "status": "active",
                    "replayed": False,
                    "retry_after_seconds": 2,
                },
            ),
            ScriptedExchange(
                "get_daily_track", {"track_id": "track_test"}, daily_track_payload(blocked=True)
            ),
            ScriptedExchange(
                "retry_daily_track",
                retry,
                {
                    "outcome": "accepted",
                    "track_id": "track_test",
                    "status": "active",
                    "replayed": False,
                    "retry_after_seconds": 2,
                },
            ),
            ScriptedExchange(
                "get_daily_track",
                {"track_id": "track_test"},
                daily_track_payload(),
            ),
            ScriptedExchange(
                "get_daily_track_result",
                {"track_id": "track_test", "section": "strategy_observations", "limit": 1},
                observation_page_1,
            ),
            ScriptedExchange(
                "get_daily_track_result",
                {
                    "track_id": "track_test",
                    "section": "strategy_observations",
                    "cursor": "track_page_2",
                    "limit": 1,
                },
                observation_page_2,
            ),
        ],
    )
    result = DeterministicTrajectoryHarness(
        model=ScriptedFakeModel(
            [
                CallTool("start_daily_track", start),
                CallTool("list_daily_tracks", {"limit": 20}),
                WaitForRetry(30),
                CallTool("get_daily_track", {"track_id": "track_test"}),
                CallTool("refresh_daily_track", refresh),
                WaitForRetry(2),
                CallTool("get_daily_track", {"track_id": "track_test"}),
                CallTool("retry_daily_track", retry),
                WaitForRetry(2),
                CallTool("get_daily_track", {"track_id": "track_test"}),
                CallTool(
                    "get_daily_track_result",
                    {"track_id": "track_test", "section": "strategy_observations", "limit": 1},
                ),
                CallTool(
                    "get_daily_track_result",
                    {
                        "track_id": "track_test",
                        "section": "strategy_observations",
                        "cursor": "track_page_2",
                        "limit": 1,
                    },
                ),
                CallTool(
                    "stop_daily_track",
                    {"track_id": "track_test", "request_id": "stop_not_granted"},
                ),
                Finish(
                    artifacts={"track_id": "track_test", "result_pages": 2},
                    product_state="daily_track_up_to_date",
                ),
            ]
        ),
        transport=transport,
        seed=44,
        fixed_uuid="00000000-0000-4000-8000-000000000044",
        max_steps=19,
        max_public_calls=11,
        max_poll_calls=3,
    ).run()

    assert result.product_state == "daily_track_up_to_date"
    assert result.virtual_time_seconds == 34
    assert result.poll_counts == {"get_daily_track": 3}
    assert any(
        item.get("action") == "local_rejection" and item.get("tool") == "stop_daily_track"
        for item in result.trajectory
    )


def test_authorized_daily_track_stop_is_selected_through_public_contract() -> None:
    tools = _discovered_tools(frozenset(ResearchAgentScope))
    arguments = {"track_id": "track_test", "request_id": "stop_track_001"}
    outcome = {
        "outcome": "accepted",
        "track_id": "track_test",
        "status": "stopped",
        "replayed": False,
        "retry_after_seconds": None,
    }
    result = DeterministicTrajectoryHarness(
        model=ScriptedFakeModel(
            [
                CallTool("stop_daily_track", arguments),
                Finish(
                    artifacts={"track_id": "track_test"},
                    product_state="daily_track_stopped",
                ),
            ]
        ),
        transport=ScriptedPublicMCP(
            tools_by_grant=[tools],
            exchanges=[ScriptedExchange("stop_daily_track", arguments, outcome)],
        ),
        seed=45,
        fixed_uuid="00000000-0000-4000-8000-000000000045",
    ).run()

    assert result.product_state == "daily_track_stopped"
    assert result.public_call_count == 1


def test_http_expiry_refresh_rediscovery_backoff_and_permanent_error_trajectory() -> None:
    safe_tools = _discovered_tools(SAFE_SCOPES)
    context = research_context_payload()
    temporary = _tool_error(
        code="TEMPORARILY_UNAVAILABLE",
        tool_name="get_research_context",
        retry_after_seconds=5,
        trace_id="trace_context_temporary",
    )
    permanent = _tool_error(
        code="INVALID_INPUT",
        tool_name="diagnose_alpha_formula",
        trace_id="trace_formula_permanent",
    )
    transport = ScriptedPublicMCP(
        tools_by_grant=[safe_tools, safe_tools],
        exchanges=[
            ScriptedExchange(
                "get_research_context", {}, AuthorizationExpired("access token expired")
            ),
            ScriptedExchange("get_research_context", {}, temporary),
            ScriptedExchange("get_research_context", {}, context),
            ScriptedExchange(
                "diagnose_alpha_formula", {"source": "unknown_alpha"}, permanent
            ),
        ],
        mode="streamable_http",
    )
    result = DeterministicTrajectoryHarness(
        model=ScriptedFakeModel(
            [
                CallTool("get_research_context", {}),
                RefreshAuthorization(),
                RediscoverTools(),
                CallTool("get_research_context", {}),
                WaitForRetry(5),
                CallTool("get_research_context", {}),
                CallTool("diagnose_alpha_formula", {"source": "unknown_alpha"}),
                Finish(
                    artifacts={"context_loaded": True, "formula_submitted": False},
                    product_state="authoring_input_rejected",
                ),
            ]
        ),
        transport=transport,
        seed=46,
        fixed_uuid="00000000-0000-4000-8000-000000000046",
        max_steps=12,
        max_public_calls=5,
    ).run()

    assert result.product_state == "authoring_input_rejected"
    assert result.virtual_time_seconds == 5
    assert result.public_call_count == 4
    assert transport.refresh_count == 1
    assert transport.discovery_count == 2
    assert [
        item.get("action")
        for item in result.trajectory
        if item.get("action") in {"refresh_authorization", "rediscover"}
    ] == ["refresh_authorization", "rediscover"]
    assert result.estimated_cost_units == 4.75


def test_trajectory_failure_is_bounded_and_saves_only_sanitized_diagnostics() -> None:
    tools = _discovered_tools(SAFE_SCOPES)
    temporary = _tool_error(
        code="TEMPORARILY_UNAVAILABLE",
        tool_name="diagnose_alpha_formula",
        retry_after_seconds=5,
        trace_id="trace_saved_for_diagnosis",
    )
    harness = DeterministicTrajectoryHarness(
        model=ScriptedFakeModel(
            [
                CallTool(
                    "diagnose_alpha_formula", {"source": "private-formula-must-not-leak"}
                ),
                CallTool(
                    "diagnose_alpha_formula", {"source": "private-formula-must-not-leak"}
                ),
            ]
        ),
        transport=ScriptedPublicMCP(
            tools_by_grant=[tools],
            exchanges=[
                ScriptedExchange(
                    "diagnose_alpha_formula",
                    {"source": "private-formula-must-not-leak"},
                    temporary,
                )
            ],
        ),
        seed=47,
        fixed_uuid="00000000-0000-4000-8000-000000000047",
        max_steps=3,
        max_public_calls=2,
    )

    with pytest.raises(TrajectoryFailure) as captured:
        harness.run()

    diagnostic = str(captured.value)
    assert "trace_saved_for_diagnosis" in diagnostic
    assert '"seed": 47' in diagnostic
    assert '"max_steps": 3' in diagnostic
    assert '"tool_envelopes"' in diagnostic
    assert '"sanitized_state"' in diagnostic
    assert "private-formula-must-not-leak" not in diagnostic
    assert '"wait_required": ["diagnose_alpha_formula", 5]' in diagnostic


def test_finish_rejects_nonterminal_or_unread_research_state() -> None:
    tools = _discovered_tools(SAFE_SCOPES)
    command = factor_command("request_nonterminal")
    harness = DeterministicTrajectoryHarness(
        model=ScriptedFakeModel(
            [
                CallTool("submit_research_run", command),
                WaitForRetry(2),
                CallTool("get_research_run", {"run_id": "run_nonterminal"}),
                Finish(
                    artifacts={
                        "run_ids": ["run_nonterminal"],
                        "result_sections": ["factor"],
                    },
                    product_state="research_results_ready",
                ),
            ]
        ),
        transport=ScriptedPublicMCP(
            tools_by_grant=[tools],
            exchanges=[
                ScriptedExchange(
                    "submit_research_run",
                    command,
                    {
                        "outcome": "accepted",
                        "run_id": "run_nonterminal",
                        "status": "queued",
                        "replayed": False,
                        "retry_after_seconds": 2,
                    },
                ),
                ScriptedExchange(
                    "get_research_run",
                    {"run_id": "run_nonterminal"},
                    run_polling_payload(
                        run_id="run_nonterminal",
                        research_kind="factor_evaluation",
                        status="running",
                    ),
                ),
            ],
        ),
        seed=48,
        fixed_uuid="00000000-0000-4000-8000-000000000048",
    )

    with pytest.raises(TrajectoryFailure):
        harness.run()


def test_harness_rejects_cursor_drift_reversed_batch_items_and_active_retry() -> None:
    tools = _discovered_tools(SAFE_SCOPES)
    page = {
        "section": "strategy_observations",
        "run_id": "run_strategy",
        "research_kind": "strategy_backtest",
        "items": [],
        "next_cursor": "expected_cursor",
    }
    cursor_harness = DeterministicTrajectoryHarness(
        model=ScriptedFakeModel(
            [
                CallTool(
                    "get_research_run_result",
                    {"run_id": "run_strategy", "section": "strategy_observations", "limit": 1},
                ),
                CallTool(
                    "get_research_run_result",
                    {
                        "run_id": "run_strategy",
                        "section": "strategy_observations",
                        "cursor": "wrong_cursor",
                        "limit": 1,
                    },
                ),
            ]
        ),
        transport=ScriptedPublicMCP(
            tools_by_grant=[tools],
            exchanges=[
                ScriptedExchange(
                    "get_research_run_result",
                    {"run_id": "run_strategy", "section": "strategy_observations", "limit": 1},
                    page,
                )
            ],
        ),
        seed=49,
        fixed_uuid="00000000-0000-4000-8000-000000000049",
    )
    with pytest.raises(TrajectoryFailure):
        cursor_harness.run()

    reversed_batch = batch_polling_payload(status="succeeded")
    reversed_batch["items"] = list(reversed(reversed_batch["items"]))
    batch_harness = DeterministicTrajectoryHarness(
        model=ScriptedFakeModel(
            [CallTool("get_research_batch", {"batch_id": "batch_test"})]
        ),
        transport=ScriptedPublicMCP(
            tools_by_grant=[tools],
            exchanges=[
                ScriptedExchange(
                    "get_research_batch",
                    {"batch_id": "batch_test"},
                    reversed_batch,
                )
            ],
        ),
        seed=50,
        fixed_uuid="00000000-0000-4000-8000-000000000050",
    )
    with pytest.raises(TrajectoryFailure):
        batch_harness.run()

    track_harness = DeterministicTrajectoryHarness(
        model=ScriptedFakeModel(
            [
                CallTool("get_daily_track", {"track_id": "track_test"}),
                CallTool(
                    "retry_daily_track",
                    {"track_id": "track_test", "request_id": "retry_active"},
                ),
            ]
        ),
        transport=ScriptedPublicMCP(
            tools_by_grant=[tools],
            exchanges=[
                ScriptedExchange(
                    "get_daily_track",
                    {"track_id": "track_test"},
                    daily_track_payload(),
                )
            ],
        ),
        seed=51,
        fixed_uuid="00000000-0000-4000-8000-000000000051",
    )
    with pytest.raises(TrajectoryFailure):
        track_harness.run()


def test_schema_failures_and_model_strings_cannot_leak_or_bloat_diagnostics() -> None:
    tools = _discovered_tools(SAFE_SCOPES)
    input_canary = "private-hypothesis-schema-canary"
    input_harness = DeterministicTrajectoryHarness(
        model=ScriptedFakeModel(
            [
                CallTool(
                    "diagnose_alpha_formula",
                    {"source": "close", "unexpected": input_canary},
                )
            ]
        ),
        transport=ScriptedPublicMCP(tools_by_grant=[tools], exchanges=[]),
        seed=52,
        fixed_uuid="00000000-0000-4000-8000-000000000052",
    )
    with pytest.raises(TrajectoryFailure) as input_failure:
        input_harness.run()
    assert input_canary not in str(input_failure.value)

    output_canary = "private-observation-schema-canary"
    output_harness = DeterministicTrajectoryHarness(
        model=ScriptedFakeModel([CallTool("get_research_context", {})]),
        transport=ScriptedPublicMCP(
            tools_by_grant=[tools],
            exchanges=[
                ScriptedExchange(
                    "get_research_context",
                    {},
                    {"unexpected": output_canary},
                )
            ],
        ),
        seed=53,
        fixed_uuid="00000000-0000-4000-8000-000000000053",
    )
    with pytest.raises(TrajectoryFailure) as output_failure:
        output_harness.run()
    assert output_canary not in str(output_failure.value)

    long_canary = "diagnostic-model-canary-" * 70_000
    for seed, model in (
        (54, ScriptedFakeModel([CallTool(long_canary, {})])),
        (55, ScriptedFakeModel([Finish(artifacts={}, product_state=long_canary)])),
    ):
        harness = DeterministicTrajectoryHarness(
            model=model,
            transport=ScriptedPublicMCP(tools_by_grant=[tools], exchanges=[]),
            seed=seed,
            fixed_uuid=f"00000000-0000-4000-8000-{seed:012d}",
            max_steps=2,
        )
        with pytest.raises(TrajectoryFailure) as captured:
            harness.run()
        diagnostic = str(captured.value)
        assert "diagnostic-model-canary" not in diagnostic
        assert len(diagnostic.encode()) <= MAX_FAILURE_DIAGNOSTIC_BYTES


def test_tool_discovery_uses_official_mcp_envelopes() -> None:
    tools = _discovered_tools(SAFE_SCOPES)

    assert len(tools) == 16
    assert {
        "cancel_research_batch",
        "cancel_research_run",
        "stop_daily_track",
    }.isdisjoint(tools)
    assert all(tool.output_schema is not None for tool in tools.values())
