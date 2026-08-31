from __future__ import annotations

from datetime import UTC, date, datetime
from itertools import count
from uuid import UUID

import anyio
from mcp.client import Client
from mcp.types import Tool

from thesistrace.alpha_language import alpha_language
from thesistrace.research_agent import (
    ResearchAgentAuthority,
    ResearchAgentCapabilityRegistry,
    ResearchAgentModules,
    ResearchAgentScope,
    create_research_agent_mcp_server,
)
from thesistrace.research_agent.models import AlphaCatalogView, ResearchContext
from thesistrace.research_batch import research_batch_polling_detail
from thesistrace.research_batch.models import (
    FactorEvaluationBatchProgress,
    ResearchBatchDetail,
    ResearchBatchExecutionTiming,
    ResearchBatchItemSummary,
    ResearchBatchScope,
)
from thesistrace.research_run.models import (
    FactorResultSection,
    ResearchRunAuthorableInput,
    ResearchRunExecutionTiming,
    ResearchRunPollingDetail,
    ResearchRunProgress,
    ResearchRunSummary,
)


class _UnusedModule:
    def __getattr__(self, name: str):
        raise AssertionError(f"trajectory contract discovery called module method: {name}")


def trajectory_registry(
    scopes: frozenset[ResearchAgentScope],
) -> ResearchAgentCapabilityRegistry:
    unused = _UnusedModule()
    return ResearchAgentCapabilityRegistry(
        authority=ResearchAgentAuthority(
            subject="trajectory-agent",
            researcher_id=UUID("018f6f7e-8342-7c9a-a4df-9a86147d2e01"),
            scopes=scopes,
        ),
        modules=ResearchAgentModules(
            data_overview=unused,
            research_folders=unused,
            alpha_language=unused,
            research_authoring=unused,
            research_runs=unused,
            research_batches=unused,
            daily_tracks=unused,
        ),
    )


def discover_public_tools(registry: ResearchAgentCapabilityRegistry) -> tuple[Tool, ...]:
    async def discover() -> tuple[Tool, ...]:
        trace_ids = count()
        server = create_research_agent_mcp_server(
            lambda _context: registry,
            event_sink=lambda _event: None,
            monotonic_ns=lambda: 0,
            subject_factory=lambda _context: registry.authority.subject,
            trace_id_factory=lambda: f"trace_discovery_{next(trace_ids)}",
            transport="stdio",
        )
        async with Client(server) as client:
            listed = await client.list_tools()
        return tuple(listed.tools)

    return anyio.run(discover)


def factor_command(request_id: str) -> dict[str, object]:
    return {
        "request_id": request_id,
        "folder_id": "folder_default",
        "name": "Factor Test",
        "formula": "close",
        "hypothesis": "Prices preserve a stable cross-sectional signal.",
        "start_date": "2024-01-02",
        "end_date": "2024-01-31",
        "universe": "top300",
        "neutralization": "none",
        "research_kind": "factor_evaluation",
    }


def factor_batch_command(request_id: str) -> dict[str, object]:
    return {
        "request_id": request_id,
        "batch_kind": "factor_evaluation",
        "start_date": "2024-01-02",
        "end_date": "2024-01-31",
        "universe": "top300",
        "neutralization": "none",
        "factors": [
            {
                "item_key": "value",
                "name": "Value Factor",
                "formula": "close",
                "hypothesis": "Prices preserve a stable cross-sectional signal.",
            }
        ],
    }


def research_context_payload() -> dict[str, object]:
    return ResearchContext.model_validate(
        {
            "data_overview": {
                "market_coverage": {"start": "2024-01-02", "end": "2024-01-31"},
                "financial_coverage": None,
                "industry_coverage": None,
                "benchmark_coverage": {
                    "start": "2010-01-04",
                    "end": "2024-01-31",
                },
                "benchmark_snapshot_sha256": "b" * 64,
                "benchmark_last_published_at": "2024-02-01T00:00:00Z",
                "data_through_session": "2024-01-31",
                "last_market_refresh_at": "2024-02-01T00:00:00Z",
                "last_financial_refresh_at": None,
                "last_industry_refresh_at": None,
                "industry_refresh_status": None,
                "industry_refresh_failure_code": None,
                "market_research_readiness": True,
                "benchmark_research_readiness": True,
                "financial_research_readiness": "ready",
                "industry_research_readiness": False,
            },
            "folders": {
                "items": [
                    {
                        "id": "folder_default",
                        "name": "Research",
                        "is_default": True,
                        "created_at": "2024-01-01T00:00:00Z",
                    }
                ],
                "next_cursor": None,
            },
            "authoring_constraints": {
                "research_kinds": ("factor_evaluation", "strategy_backtest"),
                "universes": ("top300", "top1000", "top2000", "top3000"),
                "neutralizations": ("none", "industry"),
                "holdings_count": {"minimum": 1, "maximum": 100},
                "rebalance_every_sessions": {"minimum": 1, "maximum": 20},
                "batch_items": {"minimum": 1, "maximum": 20},
                "batch_kinds": ("factor_evaluation", "strategy_sweep"),
                "formula": {
                    "maximum_length": 4096,
                    "maximum_expression_nodes": 256,
                    "maximum_expression_depth": 32,
                    "maximum_effective_lookback": 252,
                    "maximum_estimated_work": 4096,
                },
            },
        }
    ).model_dump(mode="json")


def alpha_catalog_payload() -> dict[str, object]:
    catalog = alpha_language.catalog()
    return AlphaCatalogView(
        fields=[item for item in catalog.fields if item.identifier == "close"],
        builtins=[item for item in catalog.builtins if item.identifier == "ts_mean"],
        unknown_identifiers=[],
    ).model_dump(mode="json")


def formula_diagnostics_payload(source: str) -> dict[str, object]:
    return alpha_language.diagnose(source).model_dump(mode="json")


def run_polling_payload(
    *,
    run_id: str,
    research_kind: str,
    status: str,
) -> dict[str, object]:
    summary = ResearchRunSummary(
        id=run_id,
        status=status,
        name="Test Research",
        folder_id="folder_default",
        created_at=datetime(2024, 2, 1, tzinfo=UTC),
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 31),
        formula_summary="close",
        research_kind=research_kind,
    )
    input_payload: dict[str, object] = {
        "formula": "close",
        "hypothesis": "Prices preserve a stable cross-sectional signal.",
        "start_date": date(2024, 1, 2),
        "end_date": date(2024, 1, 31),
        "universe": "top300",
        "neutralization": "none",
        "research_kind": research_kind,
    }
    if research_kind == "strategy_backtest":
        input_payload.update({"holdings_count": 10, "rebalance_every_sessions": 5})
    phase = "queued" if status == "queued" else "research"
    completed_sessions = 0 if status == "queued" else 10
    committed_chunks = 0 if status == "queued" else 1
    started_at = None if status == "queued" else datetime(2024, 2, 1, tzinfo=UTC)
    finished_at = None
    elapsed_seconds = None if status == "queued" else 10.0
    sections: tuple[str, ...] = ()
    if status == "succeeded":
        phase = "succeeded"
        completed_sessions = 22
        committed_chunks = 2
        finished_at = datetime(2024, 2, 1, 0, 0, 20, tzinfo=UTC)
        elapsed_seconds = 20.0
        sections = (
            ("factor", "provenance")
            if research_kind == "factor_evaluation"
            else (
                "factor",
                "strategy_summary",
                "strategy_observations",
                "terminal_strategy_state",
                "terminal_positions",
                "provenance",
            )
        )
    detail = ResearchRunPollingDetail(
        **summary.model_dump(),
        input=ResearchRunAuthorableInput.model_validate(input_payload),
        progress=ResearchRunProgress(
            phase=phase,
            completed_warmup_sessions=0,
            total_warmup_sessions=0,
            completed_research_sessions=completed_sessions,
            total_research_sessions=22,
            committed_chunk_count=committed_chunks,
            last_completed_research_session=(
                date(2024, 1, 31) if status == "succeeded" else None
            ),
            remaining_duration_estimate_seconds=None,
            duration_is_estimate=status != "succeeded",
        ),
        execution_timing=ResearchRunExecutionTiming(
            started_at=started_at,
            finished_at=finished_at,
            elapsed_seconds=elapsed_seconds,
            is_final=status == "succeeded",
        ),
        result_available=bool(sections),
        available_result_sections=sections,
        retry_after_seconds=None if status == "succeeded" else 2,
    )
    return detail.model_dump(mode="json")


def factor_result_payload(run_id: str) -> dict[str, object]:
    correlation = {
        "mean": 0.1,
        "sample_deviation": 0.2,
        "icir": 0.5,
        "positive_fraction": 0.6,
        "valid_session_count": 10,
    }
    horizon = {
        "summary": {
            "ic": correlation,
            "rank_ic": correlation,
            "quantile_returns": {
                "q1": -0.01,
                "q2": 0.0,
                "q3": 0.01,
                "q4": 0.02,
                "q5": 0.03,
            },
            "top_bottom_return": 0.04,
        },
        "coverage": {
            "signal_session_count": 10,
            "ic_valid_session_count": 10,
            "rank_ic_valid_session_count": 10,
            "quantile_valid_session_count": 10,
        },
    }
    return FactorResultSection.model_validate(
        {
            "run_id": run_id,
            "research_kind": "factor_evaluation",
            "factor": {
                "horizons": {
                    "1": {**horizon, "horizon": 1},
                    "5": {**horizon, "horizon": 5},
                    "20": {**horizon, "horizon": 20},
                }
            },
        }
    ).model_dump(mode="json")


def batch_polling_payload(*, status: str) -> dict[str, object]:
    items = [
        ResearchBatchItemSummary(
            ordinal=ordinal,
            item_key=item_key,
            research_run_id=run_id,
            dependency_role="factor",
            status="succeeded" if status == "succeeded" else "queued",
            outcome="succeeded" if status == "succeeded" else None,
            run_availability="available",
            task_attempt_count=1 if status == "succeeded" else 0,
        )
        for ordinal, item_key, run_id in (
            (0, "value", "run_child_value"),
            (1, "quality", "run_child_quality"),
        )
    ]
    detail = ResearchBatchDetail(
        id="batch_test",
        batch_kind="factor_evaluation",
        status=status,
        created_at=datetime(2024, 2, 1, tzinfo=UTC),
        scope=ResearchBatchScope(
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 31),
            universe="top300",
            neutralization="none",
            numeric_execution_contract="float64-v1",
            semantic_versions={"alpha_language": "1"},
            data_through_session=date(2024, 1, 31),
        ),
        progress=FactorEvaluationBatchProgress(
            completed_factor_tasks=2 if status == "succeeded" else 0,
            total_factor_tasks=2,
        ),
        execution_timing=ResearchBatchExecutionTiming(
            started_at=(datetime(2024, 2, 1, tzinfo=UTC) if status != "queued" else None),
            finished_at=(
                datetime(2024, 2, 1, 0, 0, 20, tzinfo=UTC)
                if status == "succeeded"
                else None
            ),
            elapsed_seconds=20.0 if status == "succeeded" else None,
            is_final=status == "succeeded",
        ),
        attempt=None,
        live_progress=None,
        items=items,
    )
    return research_batch_polling_detail(detail).model_dump(mode="json")


def daily_track_payload(
    *,
    blocked: bool = False,
    lagging: bool = False,
) -> dict[str, object]:
    status = "blocked" if blocked else "active"
    lag_sessions = 1 if blocked or lagging else 0
    phase = "blocked" if blocked else "waiting" if lagging else "up_to_date"
    return {
        "id": "track_test",
        "status": status,
        "origin": {
            "research_run_id": "run_strategy",
            "origin_session": "2024-01-31",
            "result_checksum_sha256": "a" * 64,
        },
        "progress": {
            "head_session": "2024-01-31",
            "data_through_session": "2024-01-31",
            "lag_sessions": lag_sessions,
            "phase": phase,
            "target_start_session": None,
            "target_end_session": None,
            "target_session_count": 0,
            "current_session": None,
            "retry_wait": False,
            "next_retry_eligible_at": None,
        },
        "timing": {
            "activated_at": "2024-02-01T00:00:00Z",
            "state_updated_at": "2024-02-01T00:00:00Z",
            "current_action_started_at": None,
            "current_action_finished_at": None,
            "observed_at": "2024-02-01T00:00:00Z",
        },
        "blocked_reason": "market data refresh is required" if blocked else None,
        "action_eligibility": {
            "refresh": lagging and not blocked,
            "retry": blocked,
            "stop": True,
        },
        "available_result_sections": [
            "factor",
            "strategy_summary",
            "strategy_observations",
            "origin",
            "provenance",
        ],
        "retry_after_seconds": None if blocked else 30,
    }


def daily_track_history_payload() -> dict[str, object]:
    return {
        "items": [
            {
                "id": "track_test",
                "status": "active",
                "seed_run_id": "run_strategy",
                "result_checksum_sha256": "a" * 64,
                "origin_session": "2024-01-31",
                "strategy_session": "2024-01-31",
            }
        ],
        "next_cursor": "track_cursor_next",
    }
