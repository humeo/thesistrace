from __future__ import annotations

from datetime import UTC, date, datetime
from itertools import count
from threading import Event

import anyio
import pytest
from jsonschema import validate
from mcp.client import Client
from mcp.types import ListToolsResult, TextContent
from mcp_types.methods import serialize_server_result
from mcp_types.version import LATEST_HANDSHAKE_VERSION
from pydantic import ValidationError

from thesistrace.alpha_language import AlphaAuthoringCatalog, FormulaDiagnostics, alpha_language
from thesistrace.data.models import DataOverview, DatasetCoverage
from thesistrace.operational_events import OperationalEvent
from thesistrace.research_agent import (
    ResearchAgentAuthority,
    ResearchAgentCapabilityRegistry,
    ResearchAgentModules,
    ResearchAgentScope,
    create_research_agent_mcp_server,
    local_operator_authority,
)
from thesistrace.research_agent.mcp_server import RESEARCH_AGENT_MAX_WIRE_RESPONSE_BYTES
from thesistrace.research_agent.registry import (
    AlphaAuthoringLanguage,
    ResearchAgentForbidden,
)
from thesistrace.research_authoring import ResearchAuthoringService
from thesistrace.research_batch.models import (
    FactorEvaluationBatchProgress,
    ResearchBatchAdmissionAccepted,
    ResearchBatchAdmissionCommand,
    ResearchBatchAdmissionIssue,
    ResearchBatchAdmissionOutcome,
    ResearchBatchAdmissionRejectedOutcome,
    ResearchBatchAttemptSummary,
    ResearchBatchCancelCommand,
    ResearchBatchCancelOutcome,
    ResearchBatchDetail,
    ResearchBatchDiagnostic,
    ResearchBatchExecutionTiming,
    ResearchBatchList,
    ResearchBatchPollingDetail,
    ResearchBatchScope,
    research_batch_polling_detail,
)
from thesistrace.research_batch.service import (
    ResearchBatchAdmissionConflict,
    ResearchBatchCancelIdempotencyConflict,
    ResearchBatchCancelStateConflict,
    ResearchBatchInvalidCursor,
    ResearchBatchTemporarilyUnavailable,
)
from thesistrace.research_folder.models import ResearchFolderList, ResearchFolderSummary
from thesistrace.research_run.models import (
    FactorResultSection,
    ProvenanceResultSection,
    ResearchRunAdmissionAccepted,
    ResearchRunAdmissionCommand,
    ResearchRunAdmissionIssue,
    ResearchRunAdmissionOutcome,
    ResearchRunAdmissionRejectedOutcome,
    ResearchRunAuthorableInput,
    ResearchRunCancelCommand,
    ResearchRunCancelOutcome,
    ResearchRunExecutionTiming,
    ResearchRunList,
    ResearchRunPollingDetail,
    ResearchRunProgress,
    ResearchRunResultSectionInput,
    ResearchRunResultSectionResponse,
    ResearchRunSummary,
    ResultDataProvenance,
    ResultExecutionProvenance,
)
from thesistrace.research_run.service import (
    ResearchRunAdmissionConflict,
    ResearchRunCancelIdempotencyConflict,
    ResearchRunCancelStateConflict,
    ResearchRunInvalidCursor,
    ResearchRunResultReadFailed,
    ResearchRunResultSectionIncompatible,
    ResearchRunResultUnavailable,
    ResearchRunTemporarilyUnavailable,
)


class _DataOverviewReader:
    def overview(self) -> DataOverview:
        return DataOverview(
            market_coverage=DatasetCoverage(
                start=date(2024, 1, 2),
                end=date(2024, 1, 31),
            ),
            financial_coverage=None,
            industry_coverage=None,
            data_through_session=date(2024, 1, 31),
            last_market_refresh_at=datetime(2024, 2, 1, tzinfo=UTC),
            last_financial_refresh_at=None,
            last_industry_refresh_at=None,
            industry_refresh_status=None,
            industry_refresh_failure_code=None,
            market_research_readiness=True,
            financial_research_readiness="ready",
            industry_research_readiness=False,
        )


class _ResearchFolderReader:
    def list(self) -> ResearchFolderList:
        return ResearchFolderList(
            items=[
                ResearchFolderSummary(
                    id="folder_default",
                    name="Research",
                    is_default=True,
                    created_at=datetime(2024, 1, 1, tzinfo=UTC),
                )
            ]
        )


class _ResearchRunReader:
    def __init__(self) -> None:
        self.list_filters: dict[str, object] | None = None
        self.admission_outcome: ResearchRunAdmissionOutcome = ResearchRunAdmissionAccepted(
            run=_run_summary(),
            replayed=False,
            retry_after_seconds=2,
        )
        self.polling_detail: ResearchRunPollingDetail | None = _polling_detail()
        self.result_section: ResearchRunResultSectionResponse | None = _factor_result_section()
        self.cancel_outcome: ResearchRunCancelOutcome | None = ResearchRunCancelOutcome(
            run=ResearchRunSummary.model_validate(
                {**_run_summary().model_dump(mode="json"), "status": "cancelled"}
            ),
            replayed=False,
            retry_after_seconds=None,
        )
        self.cancel_commands: list[tuple[str, ResearchRunCancelCommand]] = []
        self.failure: Exception | None = None

    def list(self, **filters: object) -> ResearchRunList:
        if self.failure is not None:
            raise self.failure
        self.list_filters = filters
        return ResearchRunList(items=[_run_summary()], next_cursor="cursor_next")

    def get_polling_detail(self, _run_id: str) -> ResearchRunPollingDetail | None:
        if self.failure is not None:
            raise self.failure
        return self.polling_detail

    def get_result_section(
        self,
        _query: ResearchRunResultSectionInput,
    ) -> ResearchRunResultSectionResponse | None:
        if self.failure is not None:
            raise self.failure
        return self.result_section

    def cancel(
        self,
        run_id: str,
        command: ResearchRunCancelCommand,
    ) -> ResearchRunCancelOutcome | None:
        if self.failure is not None:
            raise self.failure
        self.cancel_commands.append((run_id, command))
        return self.cancel_outcome

    def admit_with_outcome(
        self,
        _command: ResearchRunAdmissionCommand,
    ) -> ResearchRunAdmissionOutcome:
        if self.failure is not None:
            raise self.failure
        return self.admission_outcome


class _ResearchBatchReader:
    def __init__(self) -> None:
        self.list_filters: dict[str, object] | None = None
        self.admission_outcome: ResearchBatchAdmissionOutcome = ResearchBatchAdmissionAccepted(
            batch=_batch_detail(),
            replayed=False,
            retry_after_seconds=2,
        )
        self.cancel_outcome: ResearchBatchCancelOutcome | None = ResearchBatchCancelOutcome(
            batch=ResearchBatchDetail.model_validate(
                {**_batch_detail().model_dump(mode="json"), "status": "cancelled"}
            ),
            replayed=False,
            retry_after_seconds=None,
        )
        self.cancel_commands: list[tuple[str, ResearchBatchCancelCommand]] = []
        self.failure: Exception | None = None

    def list(self, *, cursor: str | None, limit: int) -> ResearchBatchList:
        if self.failure is not None:
            raise self.failure
        self.list_filters = {"cursor": cursor, "limit": limit}
        return ResearchBatchList(items=[_batch_detail()], next_cursor="batch_cursor_next")

    def get_polling_detail(self, _batch_id: str) -> ResearchBatchPollingDetail | None:
        if self.failure is not None:
            raise self.failure
        return research_batch_polling_detail(_batch_detail())

    def admit_with_outcome(
        self,
        _command: ResearchBatchAdmissionCommand,
    ) -> ResearchBatchAdmissionOutcome:
        if self.failure is not None:
            raise self.failure
        return self.admission_outcome

    def cancel_with_outcome(
        self,
        batch_id: str,
        command: ResearchBatchCancelCommand,
    ) -> ResearchBatchCancelOutcome | None:
        if self.failure is not None:
            raise self.failure
        self.cancel_commands.append((batch_id, command))
        return self.cancel_outcome


class _BlockingDataOverviewReader(_DataOverviewReader):
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()
        self.finished = Event()
        self.released_by_event_loop = False

    def overview(self) -> DataOverview:
        try:
            self.started.set()
            self.released_by_event_loop = self.release.wait(timeout=1)
            return super().overview()
        finally:
            self.finished.set()


class _ExplodingAlphaLanguage:
    def catalog(
        self,
        *,
        financial_authoring_ready: bool = True,
    ) -> AlphaAuthoringCatalog:
        del financial_authoring_ready
        raise RuntimeError("private-formula-canary")

    def diagnose(self, source: str) -> FormulaDiagnostics:
        del source
        raise RuntimeError("private-formula-canary")


def _run_summary() -> ResearchRunSummary:
    return ResearchRunSummary(
        id="run_test",
        status="queued",
        name="Test Research",
        folder_id="folder_default",
        created_at=datetime(2024, 2, 1, tzinfo=UTC),
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 31),
        formula_summary="close",
        research_kind="factor_evaluation",
    )


def _batch_detail() -> ResearchBatchDetail:
    return ResearchBatchDetail(
        id="batch_test",
        batch_kind="factor_evaluation",
        status="queued",
        created_at=datetime(2024, 2, 1, tzinfo=UTC),
        scope=ResearchBatchScope(
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 31),
            universe="top300",
            neutralization="none",
            numeric_execution_contract="float64-v1",
            semantic_versions={"alpha_language": "1"},
            data_generation_id="generation_test",
            data_through_session=date(2024, 1, 31),
        ),
        progress=FactorEvaluationBatchProgress(
            completed_factor_tasks=0,
            total_factor_tasks=1,
        ),
        execution_timing=ResearchBatchExecutionTiming(
            started_at=None,
            finished_at=None,
            elapsed_seconds=None,
            is_final=False,
        ),
        attempt=None,
        live_progress=None,
        items=[],
    )


def _polling_detail() -> ResearchRunPollingDetail:
    return ResearchRunPollingDetail(
        **_run_summary().model_dump(),
        input=ResearchRunAuthorableInput(
            formula="close",
            hypothesis="Prices preserve a stable cross-sectional signal.",
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 31),
            universe="top300",
            neutralization="none",
            research_kind="factor_evaluation",
        ),
        progress=ResearchRunProgress(
            phase="queued",
            completed_warmup_sessions=0,
            total_warmup_sessions=0,
            completed_research_sessions=0,
            total_research_sessions=22,
            committed_chunk_count=0,
        ),
        execution_timing=ResearchRunExecutionTiming(
            started_at=None,
            finished_at=None,
            elapsed_seconds=None,
            is_final=False,
        ),
        result_available=False,
        available_result_sections=(),
        retry_after_seconds=2,
    )


def _factor_result_section() -> FactorResultSection:
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
            "quantile_returns": {"q1": -0.01, "q2": 0.0, "q3": 0.01, "q4": 0.02, "q5": 0.03},
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
            "run_id": "run_test",
            "research_kind": "factor_evaluation",
            "factor": {
                "horizons": {
                    "1": {**horizon, "horizon": 1},
                    "5": {**horizon, "horizon": 5},
                    "20": {**horizon, "horizon": 20},
                }
            },
        }
    )


def _factor_command(request_id: str) -> dict[str, object]:
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


def _factor_batch_command(request_id: str) -> dict[str, object]:
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


def _registry(
    authority: ResearchAgentAuthority | None = None,
    *,
    allowed_tools: frozenset[str] | None = None,
    data_overview: _DataOverviewReader | None = None,
    selected_alpha_language: AlphaAuthoringLanguage = alpha_language,
    research_runs: _ResearchRunReader | None = None,
    research_batches: _ResearchBatchReader | None = None,
) -> ResearchAgentCapabilityRegistry:
    return ResearchAgentCapabilityRegistry(
        authority=authority or local_operator_authority(),
        modules=ResearchAgentModules(
            data_overview=data_overview or _DataOverviewReader(),
            research_folders=_ResearchFolderReader(),
            alpha_language=selected_alpha_language,
            research_authoring=ResearchAuthoringService(),
            research_runs=research_runs or _ResearchRunReader(),
            research_batches=research_batches or _ResearchBatchReader(),
        ),
        **({} if allowed_tools is None else {"allowed_tools": allowed_tools}),
    )


def test_local_operator_has_only_safe_default_scopes() -> None:
    authority = local_operator_authority()

    assert authority.subject == "local_operator"
    assert authority.scopes == {
        ResearchAgentScope.RESEARCH_READ,
        ResearchAgentScope.RESEARCH_EXECUTE,
        ResearchAgentScope.TRACKING_READ,
        ResearchAgentScope.TRACKING_EXECUTE,
    }
    assert ResearchAgentScope.RESEARCH_CANCEL not in authority.scopes
    assert ResearchAgentScope.TRACKING_STOP not in authority.scopes

    cancel_authority = local_operator_authority(enable_research_cancel=True)
    assert cancel_authority.scopes == authority.scopes | {ResearchAgentScope.RESEARCH_CANCEL}


def test_registry_filters_discovery_and_rechecks_scope_at_invocation() -> None:
    denied = _registry(ResearchAgentAuthority(subject="reader", scopes=frozenset()))

    assert denied.accessible_capabilities() == ()
    with pytest.raises(ResearchAgentForbidden, match="research:read"):
        denied.get_research_context()


def test_registry_composes_context_without_generation_or_folder_mutation() -> None:
    first = _registry().get_research_context().model_dump(mode="json")
    second = _registry().get_research_context().model_dump(mode="json")

    assert first == second
    assert first["folders"]["items"][0]["id"] == "folder_default"
    assert first["authoring_constraints"]["holdings_count"] == {
        "minimum": 1,
        "maximum": 100,
    }
    assert first["authoring_constraints"]["rebalance_every_sessions"] == {
        "minimum": 1,
        "maximum": 20,
    }
    assert first["authoring_constraints"]["batch_items"] == {
        "minimum": 1,
        "maximum": 20,
    }
    serialized = str(first).lower()
    assert "generation" not in serialized
    assert "create_folder" not in serialized
    assert "rename_folder" not in serialized
    assert "delete_folder" not in serialized


def test_registry_catalog_filter_is_bounded_sorted_and_reports_unknowns() -> None:
    catalog = _registry().get_alpha_catalog(identifiers=["ts_mean", "missing_identifier", "close"])

    assert [item.identifier for item in catalog.fields] == ["close"]
    assert [item.identifier for item in catalog.builtins] == ["ts_mean"]
    assert catalog.unknown_identifiers == ["missing_identifier"]
    with pytest.raises(ValidationError):
        _registry().get_alpha_catalog(identifiers=["close"] * 51)


def test_registry_formula_diagnostics_are_structured_and_source_ranged() -> None:
    valid = _registry().diagnose_alpha_formula("close")
    invalid = _registry().diagnose_alpha_formula("unknown_alpha + close")

    assert valid.model_dump(mode="json") == {"valid": True, "diagnostics": []}
    assert invalid.valid is False
    assert invalid.diagnostics[0].code == "UNKNOWN_IDENTIFIER"
    assert invalid.diagnostics[0].range.start.offset == 0
    assert invalid.diagnostics[0].range.end.offset == len("unknown_alpha")


def test_registry_intersects_deployment_allowlist_and_rechecks_it_on_invocation() -> None:
    registry = _registry(allowed_tools=frozenset({"get_research_context"}))

    assert [capability.name for capability in registry.accessible_capabilities()] == [
        "get_research_context"
    ]
    denied = registry.invoke(
        "get_alpha_catalog",
        {},
        trace_id="trace_allowlist",
    )

    assert denied.error is not None
    assert denied.error.code == "FORBIDDEN"


def test_in_memory_protocol_exposes_exact_tool_contract() -> None:
    anyio.run(_exercise_in_memory_protocol)


def test_in_memory_protocol_exposes_destructive_cancel_only_with_scope() -> None:
    anyio.run(_exercise_destructive_cancel_protocol)


def test_registry_projects_research_run_outcomes_and_expected_errors() -> None:
    reader = _ResearchRunReader()
    registry = _registry(research_runs=reader)

    listed = registry.invoke(
        "list_research_runs",
        {"folder_id": "folder_default", "research_kind": "factor_evaluation"},
        trace_id="trace_list",
    )
    assert listed.result is not None
    assert listed.result.model_dump(mode="json")["next_cursor"] == "cursor_next"
    assert reader.list_filters == {
        "folder_id": "folder_default",
        "research_kind": "factor_evaluation",
        "cursor": None,
        "limit": 20,
    }

    accepted = registry.invoke(
        "submit_research_run",
        _factor_command("request_accepted"),
        trace_id="trace_accepted",
    )
    assert accepted.result is not None
    assert accepted.result.model_dump(mode="json") == {
        "outcome": "accepted",
        "run_id": "run_test",
        "status": "queued",
        "replayed": False,
        "retry_after_seconds": 2,
    }

    reader.admission_outcome = ResearchRunAdmissionRejectedOutcome(
        issues=[
            ResearchRunAdmissionIssue(
                code="UNKNOWN_IDENTIFIER",
                field="formula",
                message="Unknown Alpha identifier",
            )
        ],
        replayed=True,
    )
    rejected = registry.invoke(
        "submit_research_run",
        _factor_command("request_rejected"),
        trace_id="trace_rejected",
    )
    assert rejected.result is not None
    assert rejected.result.model_dump(mode="json")["outcome"] == "rejected"
    assert rejected.result.model_dump(mode="json")["issues"][0]["code"] == ("UNKNOWN_IDENTIFIER")
    assert rejected.result.model_dump(mode="json")["replayed"] is True

    reader.failure = ResearchRunAdmissionConflict("conflicting command")
    conflict = registry.invoke(
        "submit_research_run",
        _factor_command("request_conflict"),
        trace_id="trace_conflict",
    )
    assert conflict.error is not None
    assert conflict.error.code == "IDEMPOTENCY_CONFLICT"
    assert conflict.error.retryable is False

    reader.failure = ResearchRunTemporarilyUnavailable("database unavailable")
    unavailable = registry.invoke(
        "get_research_run",
        {"run_id": "run_test"},
        trace_id="trace_unavailable",
    )
    assert unavailable.error is not None
    assert unavailable.error.code == "TEMPORARILY_UNAVAILABLE"
    assert unavailable.error.retryable is True
    assert unavailable.error.retry_after_seconds == 2

    reader.failure = ResearchRunInvalidCursor("invalid cursor")
    invalid_cursor = registry.invoke(
        "list_research_runs",
        {"cursor": "invalid"},
        trace_id="trace_invalid_cursor",
    )
    assert invalid_cursor.error is not None
    assert invalid_cursor.error.code == "INVALID_INPUT"

    reader.failure = ValueError("corrupt Product State")
    internal = registry.invoke(
        "list_research_runs",
        {},
        trace_id="trace_internal",
    )
    assert internal.error is not None
    assert internal.error.code == "INTERNAL"

    reader.failure = None
    reader.polling_detail = ResearchRunPollingDetail.model_validate(
        {
            **_polling_detail().model_dump(mode="json"),
            "status": "failed",
            "failure_reason": "Research execution failed.",
            "retry_after_seconds": None,
        }
    )
    failed = registry.invoke(
        "get_research_run",
        {"run_id": "run_failed"},
        trace_id="trace_failed",
    )
    assert failed.result is not None
    assert failed.result.model_dump(mode="json")["status"] == "failed"
    assert failed.result.model_dump(mode="json")["failure_reason"] == ("Research execution failed.")
    assert failed.result.model_dump(mode="json")["retry_after_seconds"] is None

    reader.polling_detail = None
    missing = registry.invoke(
        "get_research_run",
        {"run_id": "run_missing"},
        trace_id="trace_missing",
    )
    assert missing.error is not None
    assert missing.error.code == "NOT_FOUND"

    for failure in (
        ResearchRunResultUnavailable("not succeeded"),
        ResearchRunResultSectionIncompatible("wrong kind"),
    ):
        reader.failure = failure
        state_conflict = registry.invoke(
            "get_research_run_result",
            {"run_id": "run_test", "section": "factor"},
            trace_id="trace_result_state",
        )
        assert state_conflict.error is not None
        assert state_conflict.error.code == "STATE_CONFLICT"
        assert state_conflict.error.retryable is False

    reader.failure = ResearchRunResultReadFailed("private-object-key-canary")
    read_failure = registry.invoke(
        "get_research_run_result",
        {"run_id": "run_test", "section": "factor"},
        trace_id="trace_result_internal",
    )
    assert read_failure.error is not None
    assert read_failure.error.code == "INTERNAL"
    assert "private-object-key-canary" not in read_failure.error.message


def test_registry_maps_cancel_outcomes_authority_and_conflicts() -> None:
    reader = _ResearchRunReader()
    default_registry = _registry(research_runs=reader)
    denied = default_registry.invoke(
        "cancel_research_run",
        {"run_id": "run_test", "request_id": "cancel_request"},
        trace_id="trace_cancel_denied",
    )
    assert denied.error is not None
    assert denied.error.code == "FORBIDDEN"
    assert reader.cancel_commands == []

    authority = local_operator_authority(enable_research_cancel=True)
    registry = _registry(authority, research_runs=reader)
    accepted = registry.invoke(
        "cancel_research_run",
        {"run_id": "run_test", "request_id": " cancel_request "},
        trace_id="trace_cancel",
    )
    assert accepted.result is not None
    assert accepted.result.model_dump(mode="json") == {
        "outcome": "accepted",
        "run": {
            **_run_summary().model_dump(mode="json"),
            "status": "cancelled",
        },
        "replayed": False,
        "retry_after_seconds": None,
    }
    assert reader.cancel_commands == [
        ("run_test", ResearchRunCancelCommand(request_id="cancel_request"))
    ]

    extra_confirmation = registry.invoke(
        "cancel_research_run",
        {
            "run_id": "run_test",
            "request_id": "cancel_request",
            "confirmation_token": "host-approval-is-not-authority",
        },
        trace_id="trace_confirmation_rejected",
    )
    assert extra_confirmation.error is not None
    assert extra_confirmation.error.code == "INVALID_INPUT"

    for failure, code in (
        (
            ResearchRunCancelIdempotencyConflict("conflicting request"),
            "IDEMPOTENCY_CONFLICT",
        ),
        (ResearchRunCancelStateConflict("terminal run"), "STATE_CONFLICT"),
        (
            ResearchRunTemporarilyUnavailable("database unavailable"),
            "TEMPORARILY_UNAVAILABLE",
        ),
    ):
        reader.failure = failure
        failed = registry.invoke(
            "cancel_research_run",
            {"run_id": "run_test", "request_id": "another_request"},
            trace_id=f"trace_{code.lower()}",
        )
        assert failed.error is not None
        assert failed.error.code == code
    reader.failure = None
    reader.cancel_outcome = None
    missing = registry.invoke(
        "cancel_research_run",
        {"run_id": "run_missing", "request_id": "missing_request"},
        trace_id="trace_cancel_missing",
    )
    assert missing.error is not None
    assert missing.error.code == "NOT_FOUND"


def test_registry_projects_research_batch_outcomes_and_expected_errors() -> None:
    reader = _ResearchBatchReader()
    registry = _registry(research_batches=reader)

    listed = registry.invoke(
        "list_research_batches",
        {"cursor": "batch_cursor"},
        trace_id="trace_batch_list",
    )
    assert listed.result is not None
    assert listed.result.model_dump(mode="json")["next_cursor"] == "batch_cursor_next"
    assert reader.list_filters == {"cursor": "batch_cursor", "limit": 20}

    detail = registry.invoke(
        "get_research_batch",
        {"batch_id": "batch_test"},
        trace_id="trace_batch_get",
    )
    assert detail.result is not None
    assert detail.result.model_dump(mode="json")["retry_after_seconds"] == 2

    accepted = registry.invoke(
        "submit_research_batch",
        _factor_batch_command("batch_request_accepted"),
        trace_id="trace_batch_accepted",
    )
    assert accepted.result is not None
    assert accepted.result.model_dump(mode="json") == {
        "outcome": "accepted",
        "batch_id": "batch_test",
        "status": "queued",
        "replayed": False,
        "retry_after_seconds": 2,
    }

    reader.admission_outcome = ResearchBatchAdmissionRejectedOutcome(
        issues=[
            ResearchBatchAdmissionIssue(
                code="UNKNOWN_IDENTIFIER",
                field="factors[0].formula",
                item_key="value",
                message="Unknown Alpha identifier",
            )
        ],
        replayed=True,
    )
    rejected = registry.invoke(
        "submit_research_batch",
        _factor_batch_command("batch_request_rejected"),
        trace_id="trace_batch_rejected",
    )
    assert rejected.result is not None
    assert rejected.result.model_dump(mode="json")["outcome"] == "rejected"
    assert rejected.result.model_dump(mode="json")["issues"][0]["item_key"] == "value"
    assert rejected.result.model_dump(mode="json")["replayed"] is True

    for failure, tool, arguments, code in (
        (
            ResearchBatchAdmissionConflict("conflicting command"),
            "submit_research_batch",
            _factor_batch_command("batch_request_conflict"),
            "IDEMPOTENCY_CONFLICT",
        ),
        (
            ResearchBatchTemporarilyUnavailable("database unavailable"),
            "get_research_batch",
            {"batch_id": "batch_test"},
            "TEMPORARILY_UNAVAILABLE",
        ),
        (
            ResearchBatchInvalidCursor("invalid opaque cursor"),
            "list_research_batches",
            {"cursor": "invalid"},
            "INVALID_INPUT",
        ),
    ):
        reader.failure = failure
        failed = registry.invoke(tool, arguments, trace_id=f"trace_batch_{code.lower()}")
        assert failed.error is not None
        assert failed.error.code == code

    reader.failure = None
    original_get = reader.get_polling_detail
    reader.get_polling_detail = lambda _batch_id: None  # type: ignore[method-assign]
    missing = registry.invoke(
        "get_research_batch",
        {"batch_id": "batch_missing"},
        trace_id="trace_batch_missing",
    )
    reader.get_polling_detail = original_get  # type: ignore[method-assign]
    assert missing.error is not None
    assert missing.error.code == "NOT_FOUND"


def test_research_batch_polling_projection_removes_recovery_internals() -> None:
    detail = ResearchBatchDetail.model_validate(
        {
            **_batch_detail().model_dump(mode="json"),
            "status": "failed",
            "attempt": ResearchBatchAttemptSummary(
                id="attempt_private",
                number=2,
                status="failed",
                started_at=datetime(2024, 2, 1, tzinfo=UTC),
                finished_at=datetime(2024, 2, 1, 0, 1, tzinfo=UTC),
                diagnostic=ResearchBatchDiagnostic(
                    code="RESEARCH_BATCH_EXECUTION_FAILED",
                    category="execution",
                    message="Research Batch execution failed.",
                ),
            ).model_dump(mode="json"),
            "items": [
                {
                    "ordinal": 1,
                    "item_key": "value",
                    "research_run_id": "run_child",
                    "dependency_role": "factor",
                    "status": "failed",
                    "outcome": "failed",
                    "run_availability": "available",
                    "task_attempt_count": 2,
                    "diagnostic": {
                        "code": "RESEARCH_BATCH_EXECUTION_FAILED",
                        "category": "execution",
                        "message": "Research Batch execution failed.",
                    },
                    "deleted_at": None,
                }
            ],
        }
    )

    projected = research_batch_polling_detail(detail).model_dump(mode="json")

    assert projected["diagnostic"]["code"] == "RESEARCH_BATCH_EXECUTION_FAILED"
    assert projected["retry_after_seconds"] is None
    serialized = str(projected)
    assert "attempt_private" not in serialized
    assert "task_attempt_count" not in serialized
    assert "attempt_number" not in serialized


def test_registry_maps_research_batch_cancel_authority_and_conflicts() -> None:
    reader = _ResearchBatchReader()
    denied = _registry(research_batches=reader).invoke(
        "cancel_research_batch",
        {"batch_id": "batch_test", "request_id": "cancel_batch_request"},
        trace_id="trace_batch_cancel_denied",
    )
    assert denied.error is not None
    assert denied.error.code == "FORBIDDEN"
    assert reader.cancel_commands == []

    registry = _registry(
        local_operator_authority(enable_research_cancel=True),
        research_batches=reader,
    )
    accepted = registry.invoke(
        "cancel_research_batch",
        {"batch_id": "batch_test", "request_id": " cancel_batch_request "},
        trace_id="trace_batch_cancel",
    )
    assert accepted.result is not None
    assert accepted.result.model_dump(mode="json")["batch"]["status"] == "cancelled"
    assert reader.cancel_commands == [
        ("batch_test", ResearchBatchCancelCommand(request_id="cancel_batch_request"))
    ]

    for failure, code in (
        (
            ResearchBatchCancelIdempotencyConflict("conflicting request"),
            "IDEMPOTENCY_CONFLICT",
        ),
        (ResearchBatchCancelStateConflict("terminal batch"), "STATE_CONFLICT"),
        (
            ResearchBatchTemporarilyUnavailable("database unavailable"),
            "TEMPORARILY_UNAVAILABLE",
        ),
    ):
        reader.failure = failure
        failed = registry.invoke(
            "cancel_research_batch",
            {"batch_id": "batch_test", "request_id": "another_request"},
            trace_id=f"trace_batch_cancel_{code.lower()}",
        )
        assert failed.error is not None
        assert failed.error.code == code


def test_registry_separates_read_and_execute_discovery_and_has_no_retry_or_delete() -> None:
    reader = ResearchAgentAuthority(
        subject="reader",
        scopes=frozenset({ResearchAgentScope.RESEARCH_READ}),
    )
    executor = ResearchAgentAuthority(
        subject="executor",
        scopes=frozenset({ResearchAgentScope.RESEARCH_EXECUTE}),
    )
    canceller = ResearchAgentAuthority(
        subject="canceller",
        scopes=frozenset({ResearchAgentScope.RESEARCH_CANCEL}),
    )

    reader_tools = {capability.name for capability in _registry(reader).accessible_capabilities()}
    executor_tools = {
        capability.name for capability in _registry(executor).accessible_capabilities()
    }
    cancel_tools = {
        capability.name for capability in _registry(canceller).accessible_capabilities()
    }

    assert "submit_research_run" not in reader_tools
    assert {"list_research_runs", "get_research_run"} <= reader_tools
    assert executor_tools == {"submit_research_batch", "submit_research_run"}
    assert cancel_tools == {"cancel_research_batch", "cancel_research_run"}
    assert all("retry" not in name and "delete" not in name for name in reader_tools)
    assert all("retry" not in name and "delete" not in name for name in executor_tools)


def test_in_memory_protocol_sanitizes_unexpected_tool_failures() -> None:
    anyio.run(_exercise_sanitized_failure)


def test_in_memory_protocol_rejects_oversized_wire_response_without_truncation() -> None:
    anyio.run(_exercise_wire_response_ceiling)


def test_in_memory_protocol_rechecks_request_authority_after_discovery() -> None:
    anyio.run(_exercise_stale_discovery_authority)


def test_http_protocol_pseudonymizes_oauth_subject_in_operational_events() -> None:
    anyio.run(_exercise_oauth_subject_event)


def test_in_memory_protocol_keeps_event_loop_responsive_during_core_read() -> None:
    anyio.run(_exercise_non_blocking_core_read)


def test_in_memory_protocol_waits_for_cancelled_core_read_without_success_event() -> None:
    anyio.run(_exercise_cancelled_core_read)


async def _exercise_in_memory_protocol() -> None:
    events: list[OperationalEvent] = []
    async with Client(_server(_registry(), events=events)) as client:
        discovered = await client.list_tools()
        tools = {tool.name: tool for tool in discovered.tools}

        assert set(tools) == {
            "get_research_context",
            "get_alpha_catalog",
            "diagnose_alpha_formula",
            "list_research_runs",
            "get_research_run",
            "get_research_run_result",
            "list_research_batches",
            "get_research_batch",
            "submit_research_batch",
            "submit_research_run",
        }
        assert client.server_capabilities is not None
        assert client.server_capabilities.prompts is None
        assert client.server_capabilities.resources is None
        assert client.server_capabilities.completions is None
        assert client.server_capabilities.tasks is None
        for tool in tools.values():
            assert tool.output_schema is not None
            assert tool.output_schema["type"] == "object"
            assert len(tool.output_schema["anyOf"]) == 2
            assert tool.annotations is not None
            assert tool.annotations.destructive_hint is False
            assert tool.annotations.idempotent_hint is True
            assert tool.annotations.open_world_hint is False
            if tool.name in {"submit_research_batch", "submit_research_run"}:
                assert tool.annotations.read_only_hint is False
                discriminator = (
                    "batch_kind" if tool.name == "submit_research_batch" else "research_kind"
                )
                assert tool.input_schema["discriminator"]["propertyName"] == discriminator
                assert len(tool.input_schema["oneOf"]) == 2
                for branch in tool.input_schema["oneOf"]:
                    definition = tool.input_schema["$defs"][branch["$ref"].rsplit("/", 1)[-1]]
                    assert definition["additionalProperties"] is False
            elif tool.name == "get_research_run_result":
                assert tool.annotations.read_only_hint is True
                assert tool.input_schema["discriminator"]["propertyName"] == "section"
                assert len(tool.input_schema["oneOf"]) == 6
                for branch in tool.input_schema["oneOf"]:
                    definition = tool.input_schema["$defs"][branch["$ref"].rsplit("/", 1)[-1]]
                    assert definition["additionalProperties"] is False
            else:
                assert tool.annotations.read_only_hint is True
                assert tool.input_schema["additionalProperties"] is False
        assert tools["get_research_context"].input_schema["properties"] == {}
        assert (
            tools["get_alpha_catalog"].input_schema["properties"]["identifiers"]["anyOf"][0][
                "maxItems"
            ]
            == 50
        )
        assert (
            tools["diagnose_alpha_formula"].input_schema["properties"]["source"]["maxLength"]
            == 4096
        )
        list_schema = tools["list_research_runs"].input_schema
        assert list_schema["properties"]["limit"]["default"] == 20
        assert list_schema["properties"]["limit"]["maximum"] == 50
        assert list_schema["properties"]["cursor"]["anyOf"][0]["maxLength"] == 1024
        batch_list_schema = tools["list_research_batches"].input_schema
        assert batch_list_schema["properties"]["limit"]["default"] == 20
        assert batch_list_schema["properties"]["limit"]["maximum"] == 50
        assert batch_list_schema["properties"]["cursor"]["anyOf"][0]["maxLength"] == 1024
        batch_submit_schema = tools["submit_research_batch"].input_schema
        assert "structured rejected outcome" in (tools["submit_research_batch"].description or "")
        assert "get_research_batch" in (tools["submit_research_batch"].description or "")
        assert "retry_after_seconds" in (tools["get_research_batch"].description or "")
        for schema in (str(tools["get_research_batch"].output_schema),):
            assert "ResearchBatchAttemptSummary" not in schema
            assert "ResearchBatchLiveProgress" not in schema
            assert "task_attempt_count" not in schema
            assert "attempt_number" not in schema
            assert "diagnostic" in schema
        for branch in batch_submit_schema["oneOf"]:
            definition = batch_submit_schema["$defs"][branch["$ref"].rsplit("/", 1)[-1]]
            items_name = "factors" if "FactorEvaluation" in branch["$ref"] else "strategies"
            assert definition["properties"][items_name]["minItems"] == 1
            assert definition["properties"][items_name]["maxItems"] == 20
        submit_schema = tools["submit_research_run"].input_schema
        strategy_ref = next(
            branch["$ref"]
            for branch in submit_schema["oneOf"]
            if "StrategyBacktest" in branch["$ref"]
        )
        strategy_schema = submit_schema["$defs"][strategy_ref.rsplit("/", 1)[-1]]
        assert {"holdings_count", "rebalance_every_sessions"} <= set(strategy_schema["required"])
        result_schema = tools["get_research_run_result"].input_schema
        collection_schemas = [
            result_schema["$defs"][branch["$ref"].rsplit("/", 1)[-1]]
            for branch in result_schema["oneOf"]
            if "Observations" in branch["$ref"] or "Positions" in branch["$ref"]
        ]
        assert len(collection_schemas) == 2
        assert all(schema["properties"]["limit"]["default"] == 20 for schema in collection_schemas)
        assert all(schema["properties"]["limit"]["maximum"] == 50 for schema in collection_schemas)
        result_output_schema = tools["get_research_run_result"].output_schema
        summary_definition = result_output_schema["$defs"]["StrategySummaryResultSection"]
        metrics_ref = summary_definition["properties"]["metrics"]["$ref"]
        metrics_definition = result_output_schema["$defs"][metrics_ref.rsplit("/", 1)[-1]]
        assert metrics_definition["additionalProperties"] is False
        assert {
            "net_cumulative_return",
            "benchmark_cumulative_return",
            "annualized_excess_return",
            "maximum_drawdown",
        } <= set(metrics_definition["properties"])
        serialize_server_result(
            "tools/list",
            LATEST_HANDSHAKE_VERSION,
            ListToolsResult(tools=list(tools.values())).model_dump(
                by_alias=True,
                mode="json",
                exclude_none=True,
            ),
        )

        catalog = await client.call_tool(
            "get_alpha_catalog",
            {"identifiers": ["ts_mean", "unknown_identifier", "close"]},
        )
        assert catalog.is_error is False
        validate(catalog.structured_content, tools["get_alpha_catalog"].output_schema)
        assert catalog.structured_content["unknown_identifiers"] == ["unknown_identifier"]

        invalid = await client.call_tool(
            "diagnose_alpha_formula",
            {"source": "missing_alpha + close"},
        )
        assert invalid.is_error is False
        validate(
            invalid.structured_content,
            tools["diagnose_alpha_formula"].output_schema,
        )
        assert invalid.structured_content["valid"] is False

        malformed = await client.call_tool(
            "get_alpha_catalog",
            {"identifiers": ["close"] * 51},
        )
        assert malformed.is_error is True
        validate(
            malformed.structured_content,
            tools["get_alpha_catalog"].output_schema,
        )
        extra = await client.call_tool(
            "get_research_context",
            {"generation_id": "must-not-be-accepted"},
        )
        assert extra.is_error is True
        validate(
            extra.structured_content,
            tools["get_research_context"].output_schema,
        )

        incomplete_strategy = await client.call_tool(
            "submit_research_run",
            {
                **_factor_command("request_incomplete_strategy"),
                "research_kind": "strategy_backtest",
            },
        )
        assert incomplete_strategy.is_error is True
        assert incomplete_strategy.structured_content["code"] == "INVALID_INPUT"

        factor_result = await client.call_tool(
            "get_research_run_result",
            {"run_id": "run_test", "section": "factor"},
        )
        assert factor_result.is_error is False
        validate(
            factor_result.structured_content,
            tools["get_research_run_result"].output_schema,
        )
        assert factor_result.structured_content["units"]["horizon"] == ("research_sessions")
        invalid_section_fields = await client.call_tool(
            "get_research_run_result",
            {"run_id": "run_test", "section": "factor", "limit": 20},
        )
        assert invalid_section_fields.is_error is True
        assert invalid_section_fields.structured_content["code"] == "INVALID_INPUT"

    assert [event.context["outcome"] for event in events] == [
        "succeeded",
        "succeeded",
        "failed",
        "failed",
        "failed",
        "succeeded",
        "failed",
    ]
    assert events[2].context["failure_code"] == "INVALID_INPUT"
    assert events[3].context["failure_code"] == "INVALID_INPUT"
    assert events[4].context["failure_code"] == "INVALID_INPUT"
    assert events[6].context["failure_code"] == "INVALID_INPUT"


async def _exercise_destructive_cancel_protocol() -> None:
    reader = _ResearchRunReader()
    batch_reader = _ResearchBatchReader()
    registry = _registry(
        local_operator_authority(enable_research_cancel=True),
        research_runs=reader,
        research_batches=batch_reader,
    )
    events: list[OperationalEvent] = []
    async with Client(_server(registry, events=events)) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        cancel = tools["cancel_research_run"]
        assert cancel.annotations is not None
        assert cancel.annotations.read_only_hint is False
        assert cancel.annotations.destructive_hint is True
        assert cancel.annotations.idempotent_hint is True
        assert cancel.annotations.open_world_hint is False
        assert cancel.input_schema["additionalProperties"] is False
        assert set(cancel.input_schema["required"]) == {"run_id", "request_id"}
        assert "confirmation_token" not in cancel.input_schema["properties"]
        assert "queued or running" in (cancel.description or "")
        assert "research:cancel" in (cancel.description or "")
        assert "irreversibly" in (cancel.description or "")
        assert "get_research_run after retry_after_seconds" in (cancel.description or "")
        assert "until terminal cancelled" in (cancel.description or "")

        result = await client.call_tool(
            "cancel_research_run",
            {"run_id": "run_test", "request_id": "cancel_request"},
        )
        assert result.is_error is False
        validate(result.structured_content, cancel.output_schema)
        assert result.structured_content["run"]["status"] == "cancelled"

        rejected_confirmation = await client.call_tool(
            "cancel_research_run",
            {
                "run_id": "run_test",
                "request_id": "cancel_request",
                "confirmation_token": "not-authority",
            },
        )
        assert rejected_confirmation.is_error is True
        assert rejected_confirmation.structured_content["code"] == "INVALID_INPUT"

        batch_cancel = tools["cancel_research_batch"]
        assert batch_cancel.annotations is not None
        assert batch_cancel.annotations.read_only_hint is False
        assert batch_cancel.annotations.destructive_hint is True
        assert batch_cancel.annotations.idempotent_hint is True
        assert batch_cancel.annotations.open_world_hint is False
        assert batch_cancel.input_schema["additionalProperties"] is False
        assert set(batch_cancel.input_schema["required"]) == {"batch_id", "request_id"}
        assert "confirmation_token" not in batch_cancel.input_schema["properties"]
        assert "queued or running" in (batch_cancel.description or "")
        assert "research:cancel" in (batch_cancel.description or "")
        assert "get_research_batch polling" in (batch_cancel.description or "")
        batch_cancel_output_schema = str(batch_cancel.output_schema)
        assert "ResearchBatchAttemptSummary" not in batch_cancel_output_schema
        assert "ResearchBatchLiveProgress" not in batch_cancel_output_schema
        assert "task_attempt_count" not in batch_cancel_output_schema
        assert "attempt_number" not in batch_cancel_output_schema
        assert "diagnostic" in batch_cancel_output_schema

        batch_result = await client.call_tool(
            "cancel_research_batch",
            {"batch_id": "batch_test", "request_id": "cancel_batch_request"},
        )
        assert batch_result.is_error is False
        validate(batch_result.structured_content, batch_cancel.output_schema)
        assert batch_result.structured_content["batch"]["status"] == "cancelled"

    assert [event.context["outcome"] for event in events] == [
        "succeeded",
        "failed",
        "succeeded",
    ]


async def _exercise_sanitized_failure() -> None:
    registry = _registry(selected_alpha_language=_ExplodingAlphaLanguage())
    events: list[OperationalEvent] = []
    async with Client(_server(registry, events=events)) as client:
        result = await client.call_tool("get_alpha_catalog", {})

    assert result.is_error is True
    assert len(result.content) == 1
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text == "Tool execution failed"
    assert "private-formula-canary" not in result.content[0].text
    assert result.structured_content == {
        "code": "INTERNAL",
        "message": "Tool execution failed",
        "retryable": False,
        "trace_id": "trace_test_0",
        "retry_after_seconds": None,
    }
    assert events[0].context["failure_code"] == "INTERNAL"
    assert events[0].context["trace_id"] == "trace_test_0"
    assert "private-formula-canary" not in str(events[0].context)


async def _exercise_wire_response_ceiling() -> None:
    reader = _ResearchRunReader()
    canary = "wire-response-canary-" * 4096
    reader.result_section = ProvenanceResultSection(
        run_id="run_test",
        research_kind="factor_evaluation",
        schema_version="research-result-v1",
        immutable_input_sha256="0" * 64,
        authoring_input=ResearchRunAuthorableInput(
            formula=canary,
            hypothesis=None,
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 31),
            universe="top300",
            neutralization="none",
            research_kind="factor_evaluation",
        ),
        data=ResultDataProvenance(
            generation_id="generation_test",
            data_through_session=date(2024, 1, 31),
            financial_research_readiness="ready",
        ),
        execution=ResultExecutionProvenance(
            calculation_contracts={"numeric_execution_contract": "decimal-v1"},
            semantic_versions={"alpha": "v1"},
        ),
    )
    events: list[OperationalEvent] = []
    async with Client(_server(_registry(research_runs=reader), events=events)) as client:
        result = await client.call_tool(
            "get_research_run_result",
            {"run_id": "run_test", "section": "provenance"},
        )

    assert result.is_error is True
    assert result.structured_content["code"] == "INTERNAL"
    serialized = result.model_dump_json(by_alias=True, exclude_none=True)
    assert len(serialized.encode()) < RESEARCH_AGENT_MAX_WIRE_RESPONSE_BYTES
    assert canary not in serialized
    assert events[0].context["response_bytes"] < RESEARCH_AGENT_MAX_WIRE_RESPONSE_BYTES


async def _exercise_stale_discovery_authority() -> None:
    current = {"registry": _registry()}
    trace_ids = count()
    server = create_research_agent_mcp_server(
        lambda _context: current["registry"],
        event_sink=lambda _event: None,
        monotonic_ns=lambda: 0,
        trace_id_factory=lambda: f"trace_test_{next(trace_ids)}",
        transport="stdio",
    )
    async with Client(server) as client:
        discovered = await client.list_tools()
        assert "get_research_context" in {tool.name for tool in discovered.tools}

        current["registry"] = _registry(
            ResearchAgentAuthority(subject="reader", scopes=frozenset())
        )
        denied = await client.call_tool("get_research_context", {})

    assert denied.is_error is True
    assert denied.structured_content["code"] == "FORBIDDEN"


async def _exercise_oauth_subject_event() -> None:
    raw_subject = f"auth0|{'a' * 194}"
    events: list[OperationalEvent] = []
    registry = _registry(
        ResearchAgentAuthority(
            subject=raw_subject,
            scopes=frozenset({ResearchAgentScope.RESEARCH_READ}),
        )
    )
    trace_ids = count()
    server = create_research_agent_mcp_server(
        lambda _context: registry,
        event_sink=events.append,
        monotonic_ns=lambda: 0,
        trace_id_factory=lambda: f"trace_test_{next(trace_ids)}",
        transport="streamable_http",
    )

    async with Client(server) as client:
        first = await client.call_tool("get_research_context", {})
        second = await client.call_tool("get_research_context", {})

    assert first.is_error is False
    assert second.is_error is False
    assert len(events) == 2
    event_subjects = [event.context["subject"] for event in events]
    assert event_subjects[0] == event_subjects[1]
    assert isinstance(event_subjects[0], str)
    assert event_subjects[0].startswith("oauth_")
    assert len(event_subjects[0]) == 38
    assert raw_subject not in str(events)


async def _exercise_non_blocking_core_read() -> None:
    reader = _BlockingDataOverviewReader()
    results = []
    async with Client(_server(_registry(data_overview=reader), events=[])) as client:
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(_collect_context_result, client, results)
            with anyio.fail_after(2):
                while not reader.started.is_set():
                    await anyio.sleep(0)
            reader.release.set()

    assert reader.released_by_event_loop is True
    assert len(results) == 1
    assert results[0].is_error is False


async def _exercise_cancelled_core_read() -> None:
    reader = _BlockingDataOverviewReader()
    events: list[OperationalEvent] = []
    scopes: list[anyio.CancelScope] = []
    async with Client(_server(_registry(data_overview=reader), events=events)) as client:
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(_call_context_until_cancelled, client, scopes)
            with anyio.fail_after(2):
                while not reader.started.is_set() or not scopes:
                    await anyio.sleep(0)
            scopes[0].cancel()
            await anyio.sleep(0)
            assert reader.finished.is_set() is False
            assert not any(event.context["outcome"] == "succeeded" for event in events)
            reader.release.set()

    assert reader.finished.is_set() is True
    assert not any(event.context["outcome"] == "succeeded" for event in events)


async def _collect_context_result(client: Client, results: list) -> None:
    results.append(await client.call_tool("get_research_context", {}))


async def _call_context_until_cancelled(
    client: Client,
    scopes: list[anyio.CancelScope],
) -> None:
    with anyio.CancelScope() as scope:
        scopes.append(scope)
        await client.call_tool("get_research_context", {})


def _server(
    registry: ResearchAgentCapabilityRegistry,
    *,
    events: list[OperationalEvent],
):
    trace_ids = count()
    return create_research_agent_mcp_server(
        lambda _context: registry,
        event_sink=events.append,
        monotonic_ns=lambda: 0,
        trace_id_factory=lambda: f"trace_test_{next(trace_ids)}",
        transport="stdio",
    )
