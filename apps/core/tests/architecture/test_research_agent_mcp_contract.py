from __future__ import annotations

import json
from datetime import UTC, date, datetime
from hashlib import sha256
from itertools import count
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace
from uuid import UUID

import anyio
import pytest
from jsonschema import validate
from mcp.client import Client
from mcp.types import CallToolRequestParams, CallToolResult, ListToolsResult, TextContent
from mcp_types.methods import serialize_server_result
from mcp_types.version import LATEST_HANDSHAKE_VERSION
from pydantic import ValidationError

from thesistrace.alpha_language import AlphaAuthoringCatalog, FormulaDiagnostics, alpha_language
from thesistrace.daily_track import (
    DAILY_TRACK_RESULT_SECTIONS,
    DailyTrackDetailUnavailable,
    DailyTrackInvalidCursor,
    DailyTrackList,
    DailyTrackOriginResultSection,
    DailyTrackPollingDetail,
    DailyTrackRefreshConflict,
    DailyTrackRefreshOutcome,
    DailyTrackRefreshUnavailable,
    DailyTrackResultSectionInput,
    DailyTrackResultSectionResponse,
    DailyTrackResultUnavailable,
    DailyTrackRetryConflict,
    DailyTrackRetryOutcome,
    DailyTrackRetryUnavailable,
    DailyTrackStopConflict,
    DailyTrackStopOutcome,
    DailyTrackStopUnavailable,
    DailyTrackStrategyObservationsResultSection,
    DailyTrackSummary,
    DailyTrackTemporarilyUnavailable,
    RefreshDailyTrackCommand,
    RetryDailyTrackCommand,
    StopDailyTrackCommand,
)
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
from thesistrace.research_agent.mcp_server import (
    RESEARCH_AGENT_MAX_CALLS_PER_WINDOW,
    RESEARCH_AGENT_MAX_CONCURRENT_CALLS,
    RESEARCH_AGENT_MAX_WIRE_REQUEST_BYTES,
    RESEARCH_AGENT_MAX_WIRE_RESPONSE_BYTES,
    RESEARCH_AGENT_RATE_WINDOW_SECONDS,
    RESEARCH_AGENT_TOOL_OUTCOME_META_KEY,
    _wire_request_bytes,
    _wire_response_bytes,
)
from thesistrace.research_agent.models import ResearchAgentToolError
from thesistrace.research_agent.pagination import ResearchAgentPagination
from thesistrace.research_agent.registry import (
    RESEARCH_AGENT_TOOL_NAMES,
    AlphaAuthoringLanguage,
    ResearchAgentExpectedFailure,
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
    ResearchRunStartTrackingOutcome,
    ResearchRunSummary,
    StartTrackingCommand,
)
from thesistrace.research_run.service import (
    ResearchRunAdmissionConflict,
    ResearchRunCancelIdempotencyConflict,
    ResearchRunCancelStateConflict,
    ResearchRunInvalidCursor,
    ResearchRunResultReadFailed,
    ResearchRunResultSectionIncompatible,
    ResearchRunResultUnavailable,
    ResearchRunStartTrackingConflict,
    ResearchRunTemporarilyUnavailable,
    ResearchRunTrackingTemporarilyUnavailable,
    ResearchRunTrackingUnavailable,
)

TEST_RESEARCHER_ID = UUID("018f6f7e-8342-7c9a-a4df-9a86147d2e01")


class _DataOverviewReader:
    def overview(self) -> DataOverview:
        return DataOverview(
            generation_manifest_sha256="a" * 64,
            field_families=[],
            available_field_ids=[field.field_id for field in alpha_language.catalog().fields],
            market_coverage=DatasetCoverage(
                start=date(2024, 1, 2),
                end=date(2024, 1, 31),
            ),
            financial_coverage=None,
            industry_coverage=None,
            benchmark_coverage=DatasetCoverage(
                start=date(2010, 1, 4),
                end=date(2024, 1, 31),
            ),
            benchmark_snapshot_sha256="b" * 64,
            benchmark_last_published_at=datetime(2024, 2, 1, tzinfo=UTC),
            data_through_session=date(2024, 1, 31),
            last_market_refresh_at=datetime(2024, 2, 1, tzinfo=UTC),
            last_financial_refresh_at=None,
            last_industry_refresh_at=None,
            industry_refresh_status=None,
            industry_refresh_failure_code=None,
            market_research_readiness=True,
            benchmark_research_readiness=True,
            financial_research_readiness="ready",
            industry_research_readiness=False,
        )


class _ResearchFolderReader:
    def list(self, researcher_id: UUID) -> ResearchFolderList:
        assert researcher_id == TEST_RESEARCHER_ID
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
        self.start_outcome: ResearchRunStartTrackingOutcome | None = (
            ResearchRunStartTrackingOutcome(
                track=_daily_track_summary(),
                replayed=False,
            )
        )
        self.start_commands: list[tuple[str, StartTrackingCommand]] = []
        self.failure: Exception | None = None

    def list(self, researcher_id: UUID, **filters: object) -> ResearchRunList:
        assert researcher_id == TEST_RESEARCHER_ID
        if self.failure is not None:
            raise self.failure
        self.list_filters = filters
        return ResearchRunList(items=[_run_summary()], next_cursor="cursor_next")

    def get_polling_detail(
        self,
        researcher_id: UUID,
        _run_id: str,
    ) -> ResearchRunPollingDetail | None:
        assert researcher_id == TEST_RESEARCHER_ID
        if self.failure is not None:
            raise self.failure
        return self.polling_detail

    def get_result_section(
        self,
        researcher_id: UUID,
        _query: ResearchRunResultSectionInput,
    ) -> ResearchRunResultSectionResponse | None:
        assert researcher_id == TEST_RESEARCHER_ID
        if self.failure is not None:
            raise self.failure
        return self.result_section

    def cancel(
        self,
        researcher_id: UUID,
        run_id: str,
        command: ResearchRunCancelCommand,
    ) -> ResearchRunCancelOutcome | None:
        assert researcher_id == TEST_RESEARCHER_ID
        if self.failure is not None:
            raise self.failure
        self.cancel_commands.append((run_id, command))
        return self.cancel_outcome

    def admit_with_outcome(
        self,
        researcher_id: UUID,
        _command: ResearchRunAdmissionCommand,
    ) -> ResearchRunAdmissionOutcome:
        assert researcher_id == TEST_RESEARCHER_ID
        if self.failure is not None:
            raise self.failure
        return self.admission_outcome

    def start_tracking_with_outcome(
        self,
        researcher_id: UUID,
        run_id: str,
        command: StartTrackingCommand,
    ) -> ResearchRunStartTrackingOutcome | None:
        assert researcher_id == TEST_RESEARCHER_ID
        if self.failure is not None:
            raise self.failure
        self.start_commands.append((run_id, command))
        return self.start_outcome


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

    def list(
        self,
        researcher_id: UUID,
        *,
        cursor: str | None,
        limit: int,
    ) -> ResearchBatchList:
        assert researcher_id == TEST_RESEARCHER_ID
        if self.failure is not None:
            raise self.failure
        self.list_filters = {"cursor": cursor, "limit": limit}
        return ResearchBatchList(items=[_batch_detail()], next_cursor="batch_cursor_next")

    def get_polling_detail(
        self,
        researcher_id: UUID,
        _batch_id: str,
    ) -> ResearchBatchPollingDetail | None:
        assert researcher_id == TEST_RESEARCHER_ID
        if self.failure is not None:
            raise self.failure
        return research_batch_polling_detail(_batch_detail())

    def admit_with_outcome(
        self,
        researcher_id: UUID,
        _command: ResearchBatchAdmissionCommand,
    ) -> ResearchBatchAdmissionOutcome:
        assert researcher_id == TEST_RESEARCHER_ID
        if self.failure is not None:
            raise self.failure
        return self.admission_outcome

    def cancel_with_outcome(
        self,
        researcher_id: UUID,
        batch_id: str,
        command: ResearchBatchCancelCommand,
    ) -> ResearchBatchCancelOutcome | None:
        assert researcher_id == TEST_RESEARCHER_ID
        if self.failure is not None:
            raise self.failure
        self.cancel_commands.append((batch_id, command))
        return self.cancel_outcome


class _DailyTrackReader:
    def __init__(self) -> None:
        self.list_filters: dict[str, object] | None = None
        self.polling_detail: DailyTrackPollingDetail | None = _daily_track_polling_detail()
        self.result_section: DailyTrackResultSectionResponse | None = (
            _daily_track_observations_result_section()
        )
        self.result_query: DailyTrackResultSectionInput | None = None
        self.retry_outcome: DailyTrackRetryOutcome | None = DailyTrackRetryOutcome(
            track=_daily_track_summary(),
            replayed=False,
            retry_after_seconds=2,
        )
        self.refresh_outcome: DailyTrackRefreshOutcome | None = DailyTrackRefreshOutcome(
            track=_daily_track_summary(),
            replayed=False,
            retry_after_seconds=2,
        )
        self.stop_outcome: DailyTrackStopOutcome | None = DailyTrackStopOutcome(
            track=DailyTrackSummary.model_validate(
                {**_daily_track_summary().model_dump(mode="python"), "status": "stopped"}
            ),
            replayed=False,
            retry_after_seconds=None,
        )
        self.retry_commands: list[tuple[str, RetryDailyTrackCommand]] = []
        self.refresh_commands: list[tuple[str, RefreshDailyTrackCommand]] = []
        self.stop_commands: list[tuple[str, StopDailyTrackCommand]] = []
        self.failure: Exception | None = None

    def list(
        self,
        researcher_id: UUID,
        *,
        cursor: str | None,
        limit: int,
    ) -> DailyTrackList:
        assert researcher_id == TEST_RESEARCHER_ID
        if self.failure is not None:
            raise self.failure
        self.list_filters = {"cursor": cursor, "limit": limit}
        return DailyTrackList(items=[_daily_track_summary()], next_cursor="track_cursor_next")

    def get_polling_detail(
        self,
        researcher_id: UUID,
        _track_id: str,
    ) -> DailyTrackPollingDetail | None:
        assert researcher_id == TEST_RESEARCHER_ID
        if self.failure is not None:
            raise self.failure
        return self.polling_detail

    def get_result_section(
        self,
        researcher_id: UUID,
        query: DailyTrackResultSectionInput,
    ) -> DailyTrackResultSectionResponse | None:
        assert researcher_id == TEST_RESEARCHER_ID
        if self.failure is not None:
            raise self.failure
        self.result_query = query
        return self.result_section

    def retry_with_outcome(
        self,
        researcher_id: UUID,
        track_id: str,
        command: RetryDailyTrackCommand,
    ) -> DailyTrackRetryOutcome | None:
        assert researcher_id == TEST_RESEARCHER_ID
        if self.failure is not None:
            raise self.failure
        self.retry_commands.append((track_id, command))
        return self.retry_outcome

    def refresh_with_outcome(
        self,
        researcher_id: UUID,
        track_id: str,
        command: RefreshDailyTrackCommand,
    ) -> DailyTrackRefreshOutcome | None:
        assert researcher_id == TEST_RESEARCHER_ID
        if self.failure is not None:
            raise self.failure
        self.refresh_commands.append((track_id, command))
        return self.refresh_outcome

    def stop_with_outcome(
        self,
        researcher_id: UUID,
        track_id: str,
        command: StopDailyTrackCommand,
    ) -> DailyTrackStopOutcome | None:
        assert researcher_id == TEST_RESEARCHER_ID
        if self.failure is not None:
            raise self.failure
        self.stop_commands.append((track_id, command))
        return self.stop_outcome


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


class _ConcurrentDataOverviewReader(_DataOverviewReader):
    def __init__(self) -> None:
        self.started = 0
        self.release = Event()
        self._lock = Lock()

    def overview(self) -> DataOverview:
        with self._lock:
            self.started += 1
        if not self.release.wait(timeout=2):
            raise RuntimeError("concurrency test did not release Core read")
        return super().overview()


class _ExplodingAlphaLanguage:
    def catalog(
        self,
        *,
        available_field_ids: frozenset[str] | None = None,
        generation_manifest_sha256: str | None = None,
    ) -> AlphaAuthoringCatalog:
        del available_field_ids, generation_manifest_sha256
        raise RuntimeError(
            "private-formula-canary private-hypothesis-canary "
            "SELECT private-sql-canary FROM secret_table "
            "/private/private-path-canary credential=private-credential-canary "
            "observation=private-observation-canary position=private-position-canary"
        )

    def diagnose(self, source: str, *, context="signal") -> FormulaDiagnostics:
        del source
        raise RuntimeError("private-formula-canary")


class _OversizedAlphaLanguage:
    def catalog(
        self,
        *,
        available_field_ids: frozenset[str] | None = None,
        generation_manifest_sha256: str | None = None,
    ) -> AlphaAuthoringCatalog:
        catalog = alpha_language.catalog(
            available_field_ids=available_field_ids,
            generation_manifest_sha256=generation_manifest_sha256,
        )
        first = catalog.fields[0]
        return AlphaAuthoringCatalog(
            fields=[
                first.model_copy(
                    update={
                        "description": "wire-response-canary-"
                        * (RESEARCH_AGENT_MAX_WIRE_RESPONSE_BYTES // 10)
                    }
                )
            ],
            builtins=[],
        )

    def diagnose(self, source: str, *, context="signal") -> FormulaDiagnostics:
        return alpha_language.diagnose(source, context=context)


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


def _daily_track_summary() -> DailyTrackSummary:
    return DailyTrackSummary(
        id="track_test",
        status="active",
        seed_run_id="run_strategy",
        result_checksum_sha256="a" * 64,
        origin_session="2024-01-31",
        strategy_session="2024-01-31",
    )


def _daily_track_polling_detail() -> DailyTrackPollingDetail:
    return DailyTrackPollingDetail.model_validate(
        {
            "id": "track_test",
            "status": "active",
            "origin": {
                "research_run_id": "run_strategy",
                "origin_session": "2024-01-31",
                "result_checksum_sha256": "a" * 64,
            },
            "progress": {
                "head_session": "2024-01-31",
                "data_through_session": "2024-01-31",
                "lag_sessions": 0,
                "phase": "up_to_date",
                "target_start_session": None,
                "target_end_session": None,
                "target_session_count": 0,
                "current_session": None,
                "retry_wait": False,
                "next_retry_eligible_at": None,
            },
            "timing": {
                "activated_at": datetime(2024, 2, 1, tzinfo=UTC),
                "state_updated_at": datetime(2024, 2, 1, tzinfo=UTC),
                "current_action_started_at": None,
                "current_action_finished_at": None,
                "observed_at": datetime(2024, 2, 1, tzinfo=UTC),
            },
            "blocked_reason": None,
            "action_eligibility": {"refresh": False, "retry": False, "stop": True},
            "available_result_sections": list(DAILY_TRACK_RESULT_SECTIONS),
            "retry_after_seconds": 30,
        }
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


def _daily_track_observations_result_section() -> DailyTrackStrategyObservationsResultSection:
    return DailyTrackStrategyObservationsResultSection(
        track_id="track_test",
        items=[],
        next_cursor=None,
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
    research_folders: _ResearchFolderReader | None = None,
    research_runs: _ResearchRunReader | None = None,
    research_batches: _ResearchBatchReader | None = None,
    daily_tracks: _DailyTrackReader | None = None,
) -> ResearchAgentCapabilityRegistry:
    return ResearchAgentCapabilityRegistry(
        authority=authority or local_operator_authority(
            researcher_id=TEST_RESEARCHER_ID
        ),
        modules=ResearchAgentModules(
            pagination=ResearchAgentPagination(b"p" * 32),
            data_overview=data_overview or _DataOverviewReader(),
            research_folders=research_folders or _ResearchFolderReader(),
            alpha_language=selected_alpha_language,
            research_authoring=ResearchAuthoringService(),
            research_runs=research_runs or _ResearchRunReader(),
            research_batches=research_batches or _ResearchBatchReader(),
            daily_tracks=daily_tracks or _DailyTrackReader(),
        ),
        **({} if allowed_tools is None else {"allowed_tools": allowed_tools}),
    )


def _canonical_v1_contract() -> bytes:
    authority = ResearchAgentAuthority(
        subject="contract-auditor",
        researcher_id=TEST_RESEARCHER_ID,
        scopes=frozenset(ResearchAgentScope),
    )
    contract = [
        {
            "name": capability.name,
            "scope": capability.required_scope.value,
            "description": capability.description,
            "annotations": capability.annotations.model_dump(
                mode="json",
                by_alias=True,
                exclude_none=True,
            ),
            "input_schema": capability.input_schema(),
            "output_schema": capability.output_schema(),
        }
        for capability in _registry(authority).accessible_capabilities()
    ]
    return json.dumps(
        _canonical_contract_value(contract),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _canonical_contract_value(value):
    if isinstance(value, dict):
        return {
            key: (
                sorted(
                    (_canonical_contract_value(item) for item in member),
                    key=lambda item: json.dumps(item, sort_keys=True),
                )
                if key == "anyOf" and isinstance(member, list)
                else _canonical_contract_value(member)
            )
            for key, member in value.items()
        }
    if isinstance(value, list):
        return [_canonical_contract_value(item) for item in value]
    return value


def test_local_operator_has_only_safe_default_scopes() -> None:
    authority = local_operator_authority(researcher_id=TEST_RESEARCHER_ID)

    assert authority.subject == "local_operator"
    assert authority.scopes == {
        ResearchAgentScope.RESEARCH_READ,
        ResearchAgentScope.RESEARCH_EXECUTE,
        ResearchAgentScope.TRACKING_READ,
        ResearchAgentScope.TRACKING_EXECUTE,
    }
    assert ResearchAgentScope.RESEARCH_CANCEL not in authority.scopes
    assert ResearchAgentScope.TRACKING_STOP not in authority.scopes

    cancel_authority = local_operator_authority(
        researcher_id=TEST_RESEARCHER_ID,
        enable_research_cancel=True,
    )
    assert cancel_authority.scopes == authority.scopes | {ResearchAgentScope.RESEARCH_CANCEL}

    stop_authority = local_operator_authority(
        researcher_id=TEST_RESEARCHER_ID,
        enable_tracking_stop=True,
    )
    assert stop_authority.scopes == authority.scopes | {ResearchAgentScope.TRACKING_STOP}


def test_discovery_schemas_are_independent_across_requests() -> None:
    first = _registry().accessible_capabilities()
    expected = [(tool.input_schema(), tool.output_schema()) for tool in first]
    for tool in first:
        for schema in (tool.input_schema(), tool.output_schema()):
            schema.clear()
        # Mutating nested definitions must not affect a later request either.
        for schema in (tool.input_schema(), tool.output_schema()):
            for value in schema.values():
                if isinstance(value, dict):
                    value.clear()
    second = _registry().accessible_capabilities()
    assert [(tool.input_schema(), tool.output_schema()) for tool in second] == expected


def test_registry_filters_discovery_and_rechecks_scope_at_invocation() -> None:
    denied = _registry(
        ResearchAgentAuthority(
            subject="reader",
            researcher_id=TEST_RESEARCHER_ID,
            scopes=frozenset(),
        )
    )

    assert denied.accessible_capabilities() == ()
    with pytest.raises(ResearchAgentForbidden, match="research:read"):
        denied.get_research_context()


def test_registry_composes_context_with_frozen_data_and_without_folder_mutation() -> None:
    first = _registry().get_research_context().model_dump(mode="json")
    second = _registry().get_research_context().model_dump(mode="json")

    assert first == second
    assert first["folders"]["items"][0]["id"] == "folder_default"
    assert first["authoring_constraints"]["holdings_count"] == {
        "minimum": 1,
        "maximum": 100,
    }
    assert first["authoring_constraints"]["selection_every_sessions"] == {
        "minimum": 1,
        "maximum": 20,
    }
    assert first["authoring_constraints"]["batch_items"] == {
        "minimum": 1,
        "maximum": 20,
    }
    serialized = str(first).lower()
    assert first["data_overview"]["generation_manifest_sha256"] == "a" * 64
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


def test_registry_catalog_paginates_fields_and_builtins_as_one_collection() -> None:
    registry = _registry()
    names = ["close", "rank", "ts_mean"]
    first = registry.get_alpha_catalog(identifiers=names, limit=2)
    assert [item.identifier for item in [*first.fields, *first.builtins]] == ["close", "rank"]
    assert first.next_cursor is not None
    second = registry.get_alpha_catalog(identifiers=names, limit=2, cursor=first.next_cursor)
    assert [item.identifier for item in [*second.fields, *second.builtins]] == ["ts_mean"]
    assert second.next_cursor is None
    default = registry.get_alpha_catalog()
    assert len(default.fields) + len(default.builtins) <= 20
    assert default.next_cursor is not None
    with pytest.raises(ResearchAgentExpectedFailure):
        registry.get_alpha_catalog(identifiers=["close"], cursor=first.next_cursor)


def test_registry_context_paginates_folders_and_invalidates_changed_collections() -> None:
    folders = [
        ResearchFolderSummary(
            id=f"folder_{i:03}",
            name="研究" * 60,
            is_default=False,
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        for i in range(55)
    ]

    class FolderReader(_ResearchFolderReader):
        def list(self, researcher_id: UUID) -> ResearchFolderList:
            return ResearchFolderList(items=folders)

    registry = _registry(research_folders=FolderReader())
    first = registry.get_research_context()
    assert len(first.folders.items) == 20
    assert first.folders.next_cursor
    seen = list(first.folders.items)
    cursor = first.folders.next_cursor
    while cursor is not None:
        page = registry.get_research_context(folder_cursor=cursor)
        assert len(page.model_dump_json().encode("utf-8")) <= 32 * 1024
        seen.extend(page.folders.items)
        cursor = page.folders.next_cursor
    assert seen == folders
    folders[0] = folders[0].model_copy(update={"name": "Changed"})
    with pytest.raises(ResearchAgentExpectedFailure):
        registry.get_research_context(folder_cursor=first.folders.next_cursor)


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
        "next_tool": "get_research_run",
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


def test_cancel_receipt_is_independent_of_oversized_attached_run_detail() -> None:
    reader = _ResearchRunReader()
    assert reader.cancel_outcome is not None
    reader.cancel_outcome = reader.cancel_outcome.model_copy(update={
        "run": reader.cancel_outcome.run.model_copy(update={"name": "研究" * 100_000}),
    })
    registry = _registry(local_operator_authority(
        researcher_id=TEST_RESEARCHER_ID, enable_research_cancel=True,
    ), research_runs=reader)
    result = registry.invoke("cancel_research_run", {
        "run_id": "run_test", "request_id": "stable-cancel",
    }, trace_id="bounded-cancel")
    assert result.error is None
    assert result.result is not None
    payload = result.result.model_dump(mode="json")
    assert payload["status"] == "cancelled"
    assert payload["run_id"] == "run_test"
    assert payload["next_tool"] == "get_research_run"
    assert len(result.result.model_dump_json().encode("utf-8")) < 1024
    assert len(reader.cancel_commands) == 1


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

    authority = local_operator_authority(
        researcher_id=TEST_RESEARCHER_ID,
        enable_research_cancel=True,
    )
    registry = _registry(authority, research_runs=reader)
    accepted = registry.invoke(
        "cancel_research_run",
        {"run_id": "run_test", "request_id": " cancel_request "},
        trace_id="trace_cancel",
    )
    assert accepted.result is not None
    assert accepted.result.model_dump(mode="json") == {
        "outcome": "accepted",
        "run_id": "run_test",
        "status": "cancelled",
        "next_tool": "get_research_run",
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
        "next_tool": "get_research_batch",
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
    reader.get_polling_detail = (  # type: ignore[method-assign]
        lambda _researcher_id, _batch_id: None
    )
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
        local_operator_authority(
            researcher_id=TEST_RESEARCHER_ID,
            enable_research_cancel=True,
        ),
        research_batches=reader,
    )
    accepted = registry.invoke(
        "cancel_research_batch",
        {"batch_id": "batch_test", "request_id": " cancel_batch_request "},
        trace_id="trace_batch_cancel",
    )
    assert accepted.result is not None
    assert accepted.result.model_dump(mode="json")["status"] == "cancelled"
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


def test_registry_projects_daily_track_history_detail_start_and_expected_errors() -> None:
    run_reader = _ResearchRunReader()
    track_reader = _DailyTrackReader()
    registry = _registry(research_runs=run_reader, daily_tracks=track_reader)

    listed = registry.invoke(
        "list_daily_tracks",
        {"cursor": "track_cursor"},
        trace_id="trace_track_list",
    )
    assert listed.result is not None
    assert listed.result.model_dump(mode="json")["next_cursor"] == "track_cursor_next"
    assert track_reader.list_filters == {"cursor": "track_cursor", "limit": 20}

    detail = registry.invoke(
        "get_daily_track",
        {"track_id": "track_test"},
        trace_id="trace_track_get",
    )
    assert detail.result is not None
    projected = detail.result.model_dump(mode="json")
    assert projected["origin"]["research_run_id"] == "run_strategy"
    assert projected["available_result_sections"] == list(DAILY_TRACK_RESULT_SECTIONS)
    assert "positions" not in str(projected).lower()

    started = registry.invoke(
        "start_daily_track",
        {"run_id": "run_strategy", "request_id": " start_track_request "},
        trace_id="trace_track_start",
    )
    assert started.result is not None
    assert started.result.model_dump(mode="json") == {
        "outcome": "accepted",
        "next_tool": "get_daily_track",
        "track_id": "track_test",
        "status": "active",
        "replayed": False,
        "retry_after_seconds": 30,
    }
    assert run_reader.start_commands == [
        ("run_strategy", StartTrackingCommand(request_id="start_track_request"))
    ]

    for failure, tool, arguments, code in (
        (
            DailyTrackInvalidCursor("invalid cursor"),
            "list_daily_tracks",
            {"cursor": "invalid"},
            "INVALID_INPUT",
        ),
        (
            DailyTrackTemporarilyUnavailable("database unavailable"),
            "get_daily_track",
            {"track_id": "track_test"},
            "TEMPORARILY_UNAVAILABLE",
        ),
        (
            DailyTrackDetailUnavailable("detail unavailable"),
            "get_daily_track",
            {"track_id": "track_test"},
            "INTERNAL",
        ),
    ):
        track_reader.failure = failure
        failed = registry.invoke(tool, arguments, trace_id=f"trace_track_{code.lower()}")
        assert failed.error is not None
        assert failed.error.code == code

    track_reader.failure = None
    for failure, code in (
        (ResearchRunStartTrackingConflict("request conflict"), "IDEMPOTENCY_CONFLICT"),
        (ResearchRunTrackingUnavailable("origin unavailable"), "STATE_CONFLICT"),
        (
            ResearchRunTrackingTemporarilyUnavailable("database unavailable"),
            "TEMPORARILY_UNAVAILABLE",
        ),
    ):
        run_reader.failure = failure
        failed = registry.invoke(
            "start_daily_track",
            {"run_id": "run_strategy", "request_id": "another_request"},
            trace_id=f"trace_start_{code.lower()}",
        )
        assert failed.error is not None
        assert failed.error.code == code

    run_reader.failure = None
    run_reader.start_outcome = None
    missing = registry.invoke(
        "start_daily_track",
        {"run_id": "run_missing", "request_id": "missing_request"},
        trace_id="trace_start_missing",
    )
    assert missing.error is not None
    assert missing.error.code == "NOT_FOUND"


def test_registry_maps_daily_track_refresh_retry_stop_outcomes_authority_and_errors() -> None:
    reader = _DailyTrackReader()
    default = _registry(daily_tracks=reader)

    result = default.invoke(
        "get_daily_track_result",
        {"track_id": "track_test", "section": "strategy_observations"},
        trace_id="trace_track_result",
    )
    assert result.result == _daily_track_observations_result_section()
    assert reader.result_query is not None
    assert reader.result_query.model_dump(mode="json") == {
        "track_id": "track_test",
        "section": "strategy_observations",
        "cursor": None,
        "limit": 20,
    }

    for failure, code in (
        (DailyTrackInvalidCursor("cursor"), "INVALID_INPUT"),
        (DailyTrackResultUnavailable("state"), "STATE_CONFLICT"),
        (DailyTrackTemporarilyUnavailable("database"), "TEMPORARILY_UNAVAILABLE"),
    ):
        reader.failure = failure
        failed_result = default.invoke(
            "get_daily_track_result",
            {"track_id": "track_test", "section": "strategy_observations"},
            trace_id=f"trace_track_result_{code.lower()}",
        )
        assert failed_result.error is not None
        assert failed_result.error.code == code

    reader.failure = None
    reader.result_section = None
    missing_result = default.invoke(
        "get_daily_track_result",
        {"track_id": "track_missing", "section": "strategy_observations"},
        trace_id="trace_track_result_missing",
    )
    assert missing_result.error is not None
    assert missing_result.error.code == "NOT_FOUND"
    reader.result_section = _daily_track_observations_result_section()

    refreshed = default.invoke(
        "refresh_daily_track",
        {"track_id": "track_test", "request_id": " refresh_request "},
        trace_id="trace_track_refresh",
    )
    assert refreshed.result is not None
    assert refreshed.result.model_dump(mode="json") == {
        "outcome": "accepted",
        "next_tool": "get_daily_track",
        "track_id": "track_test",
        "status": "active",
        "replayed": False,
        "retry_after_seconds": 2,
    }
    assert reader.refresh_commands == [
        ("track_test", RefreshDailyTrackCommand(request_id="refresh_request"))
    ]

    retried = default.invoke(
        "retry_daily_track",
        {"track_id": "track_test", "request_id": " retry_request "},
        trace_id="trace_track_retry",
    )
    assert retried.result is not None
    assert retried.result.model_dump(mode="json") == {
        "outcome": "accepted",
        "next_tool": "get_daily_track",
        "track_id": "track_test",
        "status": "active",
        "replayed": False,
        "retry_after_seconds": 2,
    }
    assert reader.retry_commands == [
        ("track_test", RetryDailyTrackCommand(request_id="retry_request"))
    ]

    denied = default.invoke(
        "stop_daily_track",
        {"track_id": "track_test", "request_id": "stop_request"},
        trace_id="trace_track_stop_denied",
    )
    assert denied.error is not None
    assert denied.error.code == "FORBIDDEN"
    assert reader.stop_commands == []

    stopper = _registry(
        local_operator_authority(
            researcher_id=TEST_RESEARCHER_ID,
            enable_tracking_stop=True,
        ),
        daily_tracks=reader,
    )
    stopped = stopper.invoke(
        "stop_daily_track",
        {"track_id": "track_test", "request_id": " stop_request "},
        trace_id="trace_track_stop",
    )
    assert stopped.result is not None
    assert stopped.result.model_dump(mode="json") == {
        "outcome": "accepted",
        "next_tool": "get_daily_track",
        "track_id": "track_test",
        "status": "stopped",
        "replayed": False,
        "retry_after_seconds": None,
    }
    assert reader.stop_commands == [
        ("track_test", StopDailyTrackCommand(request_id="stop_request"))
    ]

    confirmation = stopper.invoke(
        "stop_daily_track",
        {
            "track_id": "track_test",
            "request_id": "stop_request",
            "confirmation_token": "host-confirmation-is-not-authority",
        },
        trace_id="trace_track_stop_confirmation",
    )
    assert confirmation.error is not None
    assert confirmation.error.code == "INVALID_INPUT"

    for action, failure, code in (
        (
            "refresh_daily_track",
            DailyTrackRefreshConflict("conflict"),
            "IDEMPOTENCY_CONFLICT",
        ),
        (
            "refresh_daily_track",
            DailyTrackRefreshUnavailable("state"),
            "STATE_CONFLICT",
        ),
        ("retry_daily_track", DailyTrackRetryConflict("conflict"), "IDEMPOTENCY_CONFLICT"),
        ("retry_daily_track", DailyTrackRetryUnavailable("state"), "STATE_CONFLICT"),
        ("stop_daily_track", DailyTrackStopConflict("conflict"), "IDEMPOTENCY_CONFLICT"),
        ("stop_daily_track", DailyTrackStopUnavailable("state"), "STATE_CONFLICT"),
        (
            "refresh_daily_track",
            DailyTrackTemporarilyUnavailable("database"),
            "TEMPORARILY_UNAVAILABLE",
        ),
        (
            "retry_daily_track",
            DailyTrackTemporarilyUnavailable("database"),
            "TEMPORARILY_UNAVAILABLE",
        ),
        (
            "stop_daily_track",
            DailyTrackTemporarilyUnavailable("database"),
            "TEMPORARILY_UNAVAILABLE",
        ),
    ):
        reader.failure = failure
        selected = stopper if action == "stop_daily_track" else default
        failed = selected.invoke(
            action,
            {"track_id": "track_test", "request_id": f"{action}_failure"},
            trace_id=f"trace_{action}_{code.lower()}",
        )
        assert failed.error is not None
        assert failed.error.code == code

    reader.failure = None
    reader.retry_outcome = None
    retry_missing = default.invoke(
        "retry_daily_track",
        {"track_id": "track_missing", "request_id": "retry_missing"},
        trace_id="trace_retry_missing",
    )
    assert retry_missing.error is not None
    assert retry_missing.error.code == "NOT_FOUND"
    reader.refresh_outcome = None
    refresh_missing = default.invoke(
        "refresh_daily_track",
        {"track_id": "track_missing", "request_id": "refresh_missing"},
        trace_id="trace_refresh_missing",
    )
    assert refresh_missing.error is not None
    assert refresh_missing.error.code == "NOT_FOUND"
    reader.stop_outcome = None
    stop_missing = stopper.invoke(
        "stop_daily_track",
        {"track_id": "track_missing", "request_id": "stop_missing"},
        trace_id="trace_stop_missing",
    )
    assert stop_missing.error is not None
    assert stop_missing.error.code == "NOT_FOUND"


def test_daily_track_action_outcomes_enforce_authoritative_polling_guidance() -> None:
    active = _daily_track_summary()
    blocked = DailyTrackSummary.model_validate(
        {**active.model_dump(mode="python"), "status": "blocked"}
    )
    stopping = DailyTrackSummary.model_validate(
        {**active.model_dump(mode="python"), "status": "stopping"}
    )
    stopped = DailyTrackSummary.model_validate(
        {**active.model_dump(mode="python"), "status": "stopped"}
    )

    DailyTrackRefreshOutcome(track=active, replayed=False, retry_after_seconds=2)
    DailyTrackRetryOutcome(track=active, replayed=False, retry_after_seconds=2)
    DailyTrackRetryOutcome(track=blocked, replayed=False, retry_after_seconds=None)
    DailyTrackStopOutcome(track=stopping, replayed=False, retry_after_seconds=2)
    DailyTrackStopOutcome(track=stopped, replayed=False, retry_after_seconds=None)

    for model, track, retry_after_seconds in (
        (DailyTrackRefreshOutcome, active, 1),
        (DailyTrackRefreshOutcome, blocked, 2),
        (DailyTrackRefreshOutcome, stopped, 2),
        (DailyTrackRetryOutcome, active, None),
        (DailyTrackRetryOutcome, blocked, 2),
        (DailyTrackRetryOutcome, stopped, None),
        (DailyTrackStopOutcome, stopping, None),
        (DailyTrackStopOutcome, stopped, 2),
        (DailyTrackStopOutcome, blocked, None),
    ):
        with pytest.raises(ValidationError):
            model(track=track, replayed=False, retry_after_seconds=retry_after_seconds)


def test_registry_separates_read_execute_and_destructive_tracking_discovery() -> None:
    reader = ResearchAgentAuthority(
        subject="reader",
        researcher_id=TEST_RESEARCHER_ID,
        scopes=frozenset({ResearchAgentScope.RESEARCH_READ}),
    )
    executor = ResearchAgentAuthority(
        subject="executor",
        researcher_id=TEST_RESEARCHER_ID,
        scopes=frozenset({ResearchAgentScope.RESEARCH_EXECUTE}),
    )
    canceller = ResearchAgentAuthority(
        subject="canceller",
        researcher_id=TEST_RESEARCHER_ID,
        scopes=frozenset({ResearchAgentScope.RESEARCH_CANCEL}),
    )
    tracking_reader = ResearchAgentAuthority(
        subject="tracking-reader",
        researcher_id=TEST_RESEARCHER_ID,
        scopes=frozenset({ResearchAgentScope.TRACKING_READ}),
    )
    tracking_executor = ResearchAgentAuthority(
        subject="tracking-executor",
        researcher_id=TEST_RESEARCHER_ID,
        scopes=frozenset({ResearchAgentScope.TRACKING_EXECUTE}),
    )
    tracking_stopper = ResearchAgentAuthority(
        subject="tracking-stopper",
        researcher_id=TEST_RESEARCHER_ID,
        scopes=frozenset({ResearchAgentScope.TRACKING_STOP}),
    )

    reader_tools = {capability.name for capability in _registry(reader).accessible_capabilities()}
    executor_tools = {
        capability.name for capability in _registry(executor).accessible_capabilities()
    }
    cancel_tools = {
        capability.name for capability in _registry(canceller).accessible_capabilities()
    }
    tracking_reader_tools = {
        capability.name for capability in _registry(tracking_reader).accessible_capabilities()
    }
    tracking_executor_tools = {
        capability.name for capability in _registry(tracking_executor).accessible_capabilities()
    }
    tracking_stopper_tools = {
        capability.name for capability in _registry(tracking_stopper).accessible_capabilities()
    }

    assert "submit_research_run" not in reader_tools
    assert {"list_research_runs", "get_research_run"} <= reader_tools
    assert executor_tools == {"submit_research_batch", "submit_research_run"}
    assert cancel_tools == {"cancel_research_batch", "cancel_research_run"}
    assert tracking_reader_tools == {
        "get_daily_track",
        "get_daily_track_result",
        "list_daily_tracks",
    }
    assert tracking_executor_tools == {
        "refresh_daily_track",
        "retry_daily_track",
        "start_daily_track",
    }
    assert tracking_stopper_tools == {"stop_daily_track"}
    assert all("retry" not in name and "delete" not in name for name in reader_tools)
    assert all("retry" not in name and "delete" not in name for name in executor_tools)
    assert "delete_daily_track" not in RESEARCH_AGENT_TOOL_NAMES


def test_v1_inventory_scopes_descriptions_annotations_and_schemas_are_exact() -> None:
    assert {scope.value for scope in ResearchAgentScope} == {
        "research:read",
        "research:execute",
        "research:cancel",
        "tracking:read",
        "tracking:execute",
        "tracking:stop",
    }
    assert RESEARCH_AGENT_TOOL_NAMES == {
        "get_research_context",
        "get_alpha_catalog",
        "diagnose_alpha_formula",
        "diagnose_research_spec",
        "list_research_runs",
        "get_research_run",
        "get_research_run_result",
        "list_research_batches",
        "get_research_batch",
        "submit_research_batch",
        "cancel_research_batch",
        "cancel_research_run",
        "submit_research_run",
        "list_daily_tracks",
        "get_daily_track",
        "get_daily_track_result",
        "start_daily_track",
        "refresh_daily_track",
        "retry_daily_track",
        "stop_daily_track",
    }
    canonical = _canonical_v1_contract()

    assert sha256(canonical).hexdigest() == (
        "4e50d5153dbb0f2d1033fbac3ccd54084e335d49b7889bd2431c3493f9fb2873"
    )
    assert len(canonical) == 275938


def test_v1_ingress_limits_are_fixed_and_cover_the_maximum_valid_batch() -> None:
    assert RESEARCH_AGENT_MAX_WIRE_REQUEST_BYTES == 64 * 1024 * 1024
    assert RESEARCH_AGENT_MAX_WIRE_RESPONSE_BYTES == 16 * 1024 * 1024
    assert RESEARCH_AGENT_RATE_WINDOW_SECONDS == 60
    assert RESEARCH_AGENT_MAX_CALLS_PER_WINDOW == 120
    assert RESEARCH_AGENT_MAX_CONCURRENT_CALLS == 4

    capabilities = {
        capability.name: capability
        for capability in _registry().accessible_capabilities()
    }
    assert capabilities["diagnose_alpha_formula"].input_schema()["properties"][
        "source"
    ]["maxLength"] == 4096
    for name in ("submit_research_run", "submit_research_batch"):
        assert '"maxLength": 4096' in json.dumps(
            capabilities[name].input_schema(),
            sort_keys=True,
        )
    for name in ("list_research_runs", "list_research_batches", "list_daily_tracks"):
        schema = capabilities[name].input_schema()
        assert schema["properties"]["limit"]["default"] == 20
        assert schema["properties"]["limit"]["maximum"] == 50
        assert schema["properties"]["cursor"]["anyOf"][0]["maxLength"] == 1024

    batch = _factor_batch_command("r")
    template = batch["factors"][0]
    assert isinstance(template, dict)
    batch["factors"] = [
        {
            **template,
            "item_key": f"i{index}",
            "formula": "x" * 4096,
        }
        for index in range(20)
    ]
    maximum_batch_bytes = _wire_request_bytes(
        CallToolRequestParams(
            name="submit_research_batch",
            arguments=batch,
        )
    )
    assert maximum_batch_bytes == 84536
    assert maximum_batch_bytes < RESEARCH_AGENT_MAX_WIRE_REQUEST_BYTES

    evidence = json.loads(
        Path("docs/research/research-agent-mcp-v1-ingress-benchmark.json").read_text()
    )
    canonical_contract = _canonical_v1_contract()
    assert evidence["fixed_limits"] == {
        "request_bytes": RESEARCH_AGENT_MAX_WIRE_REQUEST_BYTES,
        "response_bytes": RESEARCH_AGENT_MAX_WIRE_RESPONSE_BYTES,
        "formula_characters": 4096,
        "calls_per_window": RESEARCH_AGENT_MAX_CALLS_PER_WINDOW,
        "window_seconds": RESEARCH_AGENT_RATE_WINDOW_SECONDS,
        "concurrent_calls_per_principal": RESEARCH_AGENT_MAX_CONCURRENT_CALLS,
        "list_default_items": 20,
        "list_maximum_items": 50,
        "batch_maximum_items": 20,
        "catalog_maximum_identifiers": 50,
        "cursor_characters": 1024,
    }
    assert evidence["deterministic_payloads"] == {
        "v1_contract_sha256": sha256(canonical_contract).hexdigest(),
        "v1_contract_bytes": len(canonical_contract),
        "maximum_factor_batch_call_bytes": maximum_batch_bytes,
        "maximum_framework_batch_call_bytes": 62_887_654,
    }
    assert evidence["observed"]["maximum_resident_set_bytes"] < (
        evidence["production_envelope"]["container_memory_bytes"] // 10
    )
    assert evidence["observed"]["swaps"] == 0


def test_wire_envelope_carries_twenty_maximum_python_programs_and_explicit_state():
    from pydantic import TypeAdapter

    prefix = (
        "def decide(context, state, parameters):\n"
        "    return {'output': None, 'state': state}\n#"
    )
    source = prefix + "\x01" * (65_536 - len(prefix.encode()))
    parameters = {"payload": "\x7f" * (65_536 - len('{"payload":""}'))}
    program = {
        "source": source, "parameters": parameters,
        "data_requirements": {"field_ids": ["price.close.adjusted"], "history_sessions": 1},
    }
    batch = {
        "batch_kind": "strategy_sweep", "request_id": "maximum-python-batch",
        "start_date": "2026-08-03", "end_date": "2026-08-04", "universe": "top300",
        "strategies": [
            {"item_key": str(i), "strategy_mode": "direct", "initial_cash_cny": "100000",
             "program": program} for i in range(20)
        ],
    }
    TypeAdapter(ResearchBatchAdmissionCommand).validate_python(batch)
    assert _wire_request_bytes(CallToolRequestParams(
        name="submit_research_batch", arguments=batch,
    )) <= RESEARCH_AGENT_MAX_WIRE_REQUEST_BYTES
    # MCP returns both structured and text content. Neither may truncate a
    # valid explicit state at its 256 KiB contract limit.
    state = {"payload": "x" * (256 * 1024 - len('{"payload":""}'))}
    result = CallToolResult(
        content=[TextContent(type="text", text=json.dumps(state))], structured_content=state,
    )
    context = SimpleNamespace(protocol_version=LATEST_HANDSHAKE_VERSION, request_id="request")
    assert _wire_response_bytes(context, method="tools/call", result=result) <= (
        RESEARCH_AGENT_MAX_WIRE_RESPONSE_BYTES
    )


def test_wire_envelope_carries_twenty_frameworks_with_four_maximum_programs():
    from pydantic import TypeAdapter

    prefix = (
        "def decide(context, state, parameters):\n"
        "    return {'output': None, 'state': state}\n#"
    )
    source = prefix + "\x01" * (65_536 - len(prefix.encode()))
    program = {
        "source": source, "parameters": {"payload": "\x7f" * (65_536 - len('{"payload":""}'))},
        "data_requirements": {"field_ids": [], "history_sessions": 1},
    }
    modules = {stage: {"kind": "python", "program": program} for stage in (
        "universe_selection", "alpha", "portfolio_construction", "risk_management",
    )}
    batch = {
        "batch_kind": "strategy_sweep", "request_id": "maximum-framework-batch",
        "start_date": "2026-08-03", "end_date": "2026-08-04", "universe": "top300",
        "strategies": [{
            "item_key": str(index), "strategy_mode": "framework", "initial_cash_cny": "100000",
            "modules": modules,
        } for index in range(20)],
    }
    TypeAdapter(ResearchBatchAdmissionCommand).validate_python(batch)
    size = _wire_request_bytes(CallToolRequestParams(
        name="submit_research_batch", arguments=batch,
    ))
    assert size == 62_887_654
    assert size <= RESEARCH_AGENT_MAX_WIRE_REQUEST_BYTES


def test_mcp_origin_result_preserves_large_legal_framework_state_and_pending_target():
    checksum = "a" * 64
    target = {
        "decision_session": "2026-08-03",
        "execution": "next_research_session_open",
        "contract_checksum": checksum,
        "reason": "risk_limit",
        "allocation": None,
        "position_limits": {"equity:600001.SH": 0},
    }
    origin = DailyTrackOriginResultSection.model_validate({
        "track_id": "track_test",
        "seed_run_id": "run_test",
        "seed_research_available": True,
        "result_checksum_sha256": "b" * 64,
        "terminal_account": {
            "session": "2026-08-03",
            "gross_cash": "100000", "net_cash": "100000",
            "gross_nav": "100000", "net_nav": "100000",
            "cumulative_transaction_cost": "0",
            "research_phase": {"origin_session": "2026-08-03", "report_session_count": 1},
            "decision_state": {
                "mode": "framework", "contract_checksum": checksum,
                "selection_interval": None,
                "module_states": {
                    stage: {"payload": "x" * 240_000}
                    for stage in (
                        "universe_selection", "alpha",
                        "portfolio_construction", "risk_management",
                    )
                },
                "universe": [], "signals": [], "retained_proposal": target,
            },
            "contract_checksum": checksum,
            "pending_target": target,
        },
        "positions": [],
        "next_cursor": None,
    })
    reader = _DailyTrackReader()
    reader.result_section = origin
    anyio.run(_read_large_origin_through_mcp, reader, origin)


async def _read_large_origin_through_mcp(
    reader: _DailyTrackReader, origin: DailyTrackOriginResultSection,
) -> None:
    async with Client(_server(_registry(daily_tracks=reader), events=[])) as client:
        response = await client.call_tool(
            "get_daily_track_result", {"track_id": "track_test", "section": "origin"},
        )
    assert not response.is_error
    assert response.structured_content == origin.model_dump(mode="json")
    assert json.loads(response.content[0].text) == response.structured_content
    assert len(response.content[0].text.encode()) > 900_000


@pytest.mark.parametrize("page_mebibytes", [2, 4])
def test_wire_response_preserves_complete_event_pages_in_both_mcp_representations(page_mebibytes):
    # Targets use 2 MiB and Framework uses 4 MiB plus 32 KiB metadata. Backslashes
    # exercise the extra escaping in MCP's text representation.
    payload = {"page": "\\" * ((page_mebibytes * 1024 * 1024 + 32 * 1024) // 2 - 16)}
    encoded = json.dumps(payload, separators=(",", ":"))
    assert len(encoded) <= page_mebibytes * 1024 * 1024 + 32 * 1024
    result = CallToolResult(
        content=[TextContent(type="text", text=encoded)], structured_content=payload,
    )
    context = SimpleNamespace(protocol_version=LATEST_HANDSHAKE_VERSION, request_id="request")
    assert _wire_response_bytes(context, method="tools/call", result=result) < (
        RESEARCH_AGENT_MAX_WIRE_RESPONSE_BYTES
    )


def test_v1_response_ceiling_counts_the_exact_jsonrpc_envelope() -> None:
    context = SimpleNamespace(
        protocol_version=LATEST_HANDSHAKE_VERSION,
        request_id="request-" + "i" * 1024,
    )

    def result(payload_characters: int) -> CallToolResult:
        return CallToolResult(
            content=[TextContent(type="text", text="Structured result is available.")],
            structured_content={"payload": "x" * payload_characters},
        )

    base_bytes = _wire_response_bytes(
        context,  # type: ignore[arg-type]
        method="tools/call",
        result=result(0),
    )
    exact_payload = RESEARCH_AGENT_MAX_WIRE_RESPONSE_BYTES - base_bytes
    assert _wire_response_bytes(
        context,  # type: ignore[arg-type]
        method="tools/call",
        result=result(exact_payload),
    ) == RESEARCH_AGENT_MAX_WIRE_RESPONSE_BYTES
    assert _wire_response_bytes(
        context,  # type: ignore[arg-type]
        method="tools/call",
        result=result(exact_payload + 1),
    ) == RESEARCH_AGENT_MAX_WIRE_RESPONSE_BYTES + 1


def test_v1_contract_has_no_forbidden_generic_or_compatibility_surface() -> None:
    serialized = json.dumps(
        [
            {
                "name": capability.name,
                "description": capability.description,
                "input": capability.input_schema(),
                "output": capability.output_schema(),
            }
            for capability in _registry(
                ResearchAgentAuthority(
                    subject="contract-auditor",
                    researcher_id=TEST_RESEARCHER_ID,
                    scopes=frozenset(ResearchAgentScope),
                )
            ).accessible_capabilities()
        ],
        sort_keys=True,
    ).lower()
    for forbidden in (
        "delete_research_run",
        "retry_research_run",
        "delete_daily_track",
        "mutate_folder",
        "delete_folder",
        "data_operator",
        "execute_sql",
        "execute_python",
        "execute_shell",
        "http_request",
        "object_storage",
        "get_research_batch_result",
        "confirmation_token",
    ):
        assert forbidden not in serialized


def test_stop_daily_track_is_destructive_closed_world_and_has_no_confirmation_field() -> None:
    registry = _registry(
        local_operator_authority(
            researcher_id=TEST_RESEARCHER_ID,
            enable_tracking_stop=True,
        )
    )
    tool = next(
        capability
        for capability in registry.accessible_capabilities()
        if capability.name == "stop_daily_track"
    )

    assert tool.annotations.read_only_hint is False
    assert tool.annotations.destructive_hint is True
    assert tool.annotations.idempotent_hint is True
    assert tool.annotations.open_world_hint is False
    assert tool.input_schema()["additionalProperties"] is False
    assert "confirmation_token" not in str(tool.input_schema())
    assert "tracking:stop" in tool.description


def test_structured_error_retry_contract_is_fail_closed() -> None:
    for invalid in (
        {
            "code": "TEMPORARILY_UNAVAILABLE",
            "message": "Tool is temporarily unavailable",
            "retryable": False,
            "trace_id": "trace_invalid_temporary",
        },
        {
            "code": "INVALID_INPUT",
            "message": "Tool input is invalid",
            "retryable": True,
            "retry_after_seconds": 2,
            "trace_id": "trace_invalid_permanent",
        },
    ):
        with pytest.raises(ValidationError):
            ResearchAgentToolError.model_validate(
                {
                    **invalid,
                    "context": {"tool_name": "get_research_context"},
                }
            )


def test_in_memory_protocol_sanitizes_unexpected_tool_failures() -> None:
    anyio.run(_exercise_sanitized_failure)


def test_in_memory_protocol_ignores_operational_event_sink_failure() -> None:
    anyio.run(_exercise_event_sink_failure)


def test_in_memory_protocol_maps_registry_factory_failure_to_internal() -> None:
    anyio.run(_exercise_registry_factory_failure)


def test_in_memory_protocol_emits_only_safe_call_context() -> None:
    anyio.run(_exercise_safe_call_context)


def test_stdio_and_http_event_context_is_total_for_unicode_surrogates() -> None:
    anyio.run(_exercise_surrogate_context)


def test_stdio_and_http_transports_share_structured_business_outcomes() -> None:
    anyio.run(_exercise_transport_business_outcomes)


def test_in_memory_protocol_rejects_oversized_wire_response_without_truncation() -> None:
    anyio.run(_exercise_wire_response_ceiling)


def test_in_memory_protocol_rejects_oversized_wire_request_before_registry() -> None:
    anyio.run(_exercise_wire_request_ceiling)


def test_in_memory_protocol_rate_limits_each_principal_independently() -> None:
    anyio.run(_exercise_principal_rate_limit)


def test_in_memory_protocol_caps_concurrent_calls_per_principal() -> None:
    anyio.run(_exercise_principal_concurrency_limit)


def test_concurrent_calls_remain_counted_across_rate_window_rollover() -> None:
    anyio.run(_exercise_concurrency_across_rate_window)


def test_cancelled_calls_release_concurrency_slots() -> None:
    anyio.run(_exercise_cancelled_calls_release_concurrency)


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
            "diagnose_research_spec",
            "list_research_runs",
            "get_research_run",
            "get_research_run_result",
            "list_daily_tracks",
            "get_daily_track",
            "get_daily_track_result",
            "start_daily_track",
            "refresh_daily_track",
            "retry_daily_track",
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
            error_definition = tool.output_schema["$defs"]["ResearchAgentToolError"]
            assert "context" in error_definition["required"]
            assert tool.annotations is not None
            assert tool.annotations.destructive_hint is False
            assert tool.annotations.idempotent_hint is (
                tool.name not in {"get_research_run_result", "get_daily_track_result"}
            )
            assert tool.annotations.open_world_hint is False
            if tool.name in {
                "start_daily_track",
                "refresh_daily_track",
                "retry_daily_track",
                "submit_research_batch",
                "submit_research_run",
            }:
                assert tool.annotations.read_only_hint is False
                if tool.name in {
                    "start_daily_track",
                    "refresh_daily_track",
                    "retry_daily_track",
                }:
                    assert tool.input_schema["additionalProperties"] is False
                    if tool.name == "start_daily_track":
                        assert "non-succeeded" in tool.description
                        assert "duplicate origins" in tool.description
                        assert "active capacity" in tool.description
                    elif tool.name == "retry_daily_track":
                        assert "blocked" in tool.description
                    else:
                        assert "latest available Dataset Head" in tool.description
                        assert "another Refresh" in tool.description
                    assert "get_daily_track" in tool.description
                    assert "retry_after_seconds" in tool.description
                    continue
                discriminator = (
                    "batch_kind" if tool.name == "submit_research_batch" else "research_kind"
                )
                schema = tool.input_schema
                if tool.name == "submit_research_run":
                    assert len(schema["anyOf"]) == 2
                    source = schema["$defs"]["CurrentDataRerunCommand"]
                    assert source["additionalProperties"] is False
                    assert set(source["required"]) == {"request_id", "folder_id", "rerun_source"}
                    assert "rerun_source" in tool.description
                    schema = schema["$defs"]["ResearchRunAdmissionCommand"]
                if tool.name == "submit_research_run":
                    # Research kind plus strategy mode selects the concrete
                    # command; JSON Schema represents its three exact branches.
                    assert len(schema["oneOf"]) == 3
                    direct = tool.input_schema["$defs"]["DirectStrategyAdmissionCommand"]
                    assert direct["properties"]["strategy_mode"]["const"] == "direct"
                    assert "program" in direct["required"]
                    assert "formula" not in direct["properties"]
                else:
                    assert schema["discriminator"]["propertyName"] == discriminator
                    assert len(schema["oneOf"]) == 2
                for branch in schema["oneOf"]:
                    definition = tool.input_schema["$defs"][branch["$ref"].rsplit("/", 1)[-1]]
                    assert definition["additionalProperties"] is False
            elif tool.name in {"get_research_run_result", "get_daily_track_result"}:
                assert tool.annotations.read_only_hint is False
                assert tool.annotations.idempotent_hint is False
                assert tool.input_schema["discriminator"]["propertyName"] == "section"
                expected_section_count = 18 if tool.name == "get_research_run_result" else 14
                assert len(tool.input_schema["oneOf"]) == expected_section_count
                for branch in tool.input_schema["oneOf"]:
                    definition = tool.input_schema["$defs"][branch["$ref"].rsplit("/", 1)[-1]]
                    assert definition["additionalProperties"] is False
            else:
                assert tool.annotations.read_only_hint is True
                assert tool.input_schema["additionalProperties"] is False
        assert set(tools["get_research_context"].input_schema["properties"]) == {
            "folder_cursor",
            "folder_limit",
        }
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
        track_list_schema = tools["list_daily_tracks"].input_schema
        assert track_list_schema["properties"]["limit"]["default"] == 20
        assert track_list_schema["properties"]["limit"]["maximum"] == 50
        assert track_list_schema["properties"]["cursor"]["anyOf"][0]["maxLength"] == 1024
        track_output_schema = str(tools["get_daily_track"].output_schema)
        for private_name in (
            "positions",
            "checkpoint",
            "attempt",
            "lease",
            "fence",
        ):
            assert private_name not in track_output_schema.lower()
        assert "available_result_sections" in track_output_schema
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
        assert "structured rejected outcome" in (
            tools["submit_research_run"].description or ""
        )
        assert "get_research_run" in (tools["submit_research_run"].description or "")
        strategy_ref = next(
            branch["$ref"]
            for branch in submit_schema["$defs"]["ResearchRunAdmissionCommand"]["oneOf"]
            if "StrategyBacktest" in branch["$ref"]
        )
        strategy_schema = submit_schema["$defs"][strategy_ref.rsplit("/", 1)[-1]]
        assert "initial_cash_cny" in strategy_schema["required"]
        assert {"modules", "holdings_count", "selection_every_sessions"} <= set(
            strategy_schema["properties"]
        )
        assert not {"holdings_count", "selection_every_sessions"} & set(strategy_schema["required"])
        assert strategy_schema["properties"]["initial_cash_cny"]["type"] == "string"
        result_schema = tools["get_research_run_result"].input_schema
        collection_schemas = [
            result_schema["$defs"][branch["$ref"].rsplit("/", 1)[-1]]
            for branch in result_schema["oneOf"]
            if any(name in branch["$ref"] for name in ("Observations", "Positions", "Periods"))
        ]
        assert len(collection_schemas) == 5
        assert all(schema["properties"]["limit"]["default"] == 20 for schema in collection_schemas)
        assert all(schema["properties"]["limit"]["maximum"] == 50 for schema in collection_schemas)
        assert all(
            schema["properties"]["cursor"]["anyOf"][0]["maxLength"] == 1024
            for schema in collection_schemas
        )
        track_result_schema = tools["get_daily_track_result"].input_schema
        track_collection_schemas = [
            track_result_schema["$defs"][branch["$ref"].rsplit("/", 1)[-1]]
            for branch in track_result_schema["oneOf"]
            if "Observations" in branch["$ref"] or "Origin" in branch["$ref"]
        ]
        assert len(track_collection_schemas) == 3
        for schema in track_collection_schemas:
            assert schema["properties"]["limit"]["default"] == 20
            assert schema["properties"]["limit"]["maximum"] == 50
            assert schema["properties"]["cursor"]["anyOf"][0]["maxLength"] == 1024
        track_result_output_schema = str(tools["get_daily_track_result"].output_schema).lower()
        # One public opaque checkpoint identity is required to pin explicit reruns.
        track_result_output_schema = track_result_output_schema.replace(
            "checkpoint_manifest_sha256", "",
        ).replace("checkpoint manifest sha256", "")
        for private_name in (
            "generation_id",
            "manifest",
            "object_key",
            "working_cache",
            "checkpoint",
            "attempt",
            "lease",
            "sql",
            "filesystem_path",
        ):
            assert private_name not in track_result_output_schema
        track_result_definitions = tools["get_daily_track_result"].output_schema["$defs"]
        assert "DailyTrackFactorMetrics" not in track_result_definitions
        assert track_result_definitions["DailyTrackStrategyMetrics"][
            "additionalProperties"
        ] is False
        result_output_schema = tools["get_research_run_result"].output_schema
        summary_definition = result_output_schema["$defs"]["StrategySummaryResultSection"]
        metrics_ref = summary_definition["properties"]["metrics"]["$ref"]
        metrics_definition = result_output_schema["$defs"][metrics_ref.rsplit("/", 1)[-1]]
        assert metrics_definition["additionalProperties"] is False
        assert {
            "net_cumulative_return",
            "maximum_drawdown",
        } <= set(metrics_definition["properties"])
        assert {
            "benchmark_cumulative_return",
            "benchmark_cagr",
            "annualized_excess_return",
        }.isdisjoint(metrics_definition["properties"])
        comparison_definition = result_output_schema["$defs"][
            "AvailableStrategyComparisonSummary"
        ]
        assert set(comparison_definition["properties"]) == {
            "status",
            "benchmark",
            "entry",
            "terminal",
            "metrics",
        }
        assert "curves" not in str(summary_definition).lower()
        assert "selected_universe_equal_weight" not in str(result_output_schema).lower()
        assert "benchmark_nav" not in str(result_output_schema).lower()
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
        assert isinstance(catalog.content[0], TextContent)
        assert json.loads(catalog.content[0].text) == catalog.structured_content
        assert catalog.meta is not None
        assert (
            catalog.meta[RESEARCH_AGENT_TOOL_OUTCOME_META_KEY] == "succeeded"
        )

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

        track_observations_result = await client.call_tool(
            "get_daily_track_result",
            {"track_id": "track_test", "section": "strategy_observations"},
        )
        assert track_observations_result.is_error is False
        validate(
            track_observations_result.structured_content,
            tools["get_daily_track_result"].output_schema,
        )
        assert track_observations_result.structured_content["items"] == []
        invalid_track_section_fields = await client.call_tool(
            "get_daily_track_result",
            {"track_id": "track_test", "section": "strategy_observations", "limit": 51},
        )
        assert invalid_track_section_fields.is_error is True
        assert invalid_track_section_fields.structured_content["code"] == "INVALID_INPUT"

    assert [event.context["outcome"] for event in events] == [
        "succeeded",
        "succeeded",
        "failed",
        "failed",
        "failed",
        "succeeded",
        "failed",
        "succeeded",
        "failed",
    ]
    assert events[2].context["failure_code"] == "INVALID_INPUT"
    assert events[3].context["failure_code"] == "INVALID_INPUT"
    assert events[4].context["failure_code"] == "INVALID_INPUT"
    assert events[6].context["failure_code"] == "INVALID_INPUT"
    assert events[8].context["failure_code"] == "INVALID_INPUT"
    assert events[4].context["request_id"].startswith("request_")
    assert events[5].context["run_id"] == "run_test"
    assert events[6].context["run_id"].startswith("run_id_")
    assert events[7].context["track_id"] == "track_test"
    assert events[8].context["track_id"].startswith("track_id_")


async def _exercise_destructive_cancel_protocol() -> None:
    reader = _ResearchRunReader()
    batch_reader = _ResearchBatchReader()
    registry = _registry(
        local_operator_authority(
            researcher_id=TEST_RESEARCHER_ID,
            enable_research_cancel=True,
        ),
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
        assert result.structured_content["status"] == "cancelled"

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
        assert "diagnostic" not in batch_cancel_output_schema
        assert "next_tool" in batch_cancel_output_schema

        batch_result = await client.call_tool(
            "cancel_research_batch",
            {"batch_id": "batch_test", "request_id": "cancel_batch_request"},
        )
        assert batch_result.is_error is False
        validate(batch_result.structured_content, batch_cancel.output_schema)
        assert batch_result.structured_content["status"] == "cancelled"

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
    assert json.loads(result.content[0].text) == result.structured_content
    assert "private-formula-canary" not in result.content[0].text
    assert result.meta is not None
    assert result.meta[RESEARCH_AGENT_TOOL_OUTCOME_META_KEY] == "failed"
    assert result.structured_content == {
        "code": "INTERNAL",
        "message": "Tool execution failed",
        "retryable": False,
        "trace_id": "trace_test_0",
        "retry_after_seconds": None,
        "context": {
            "tool_name": "get_alpha_catalog",
            "run_id": None,
            "batch_id": None,
            "track_id": None,
            "request_id": None,
        },
    }
    assert events[0].context["failure_code"] == "INTERNAL"
    assert events[0].context["trace_id"] == "trace_test_0"
    serialized_diagnostics = str(result.model_dump()) + str(events[0].context)
    for canary in (
        "private-formula-canary",
        "private-hypothesis-canary",
        "private-sql-canary",
        "private-path-canary",
        "private-credential-canary",
        "private-observation-canary",
        "private-position-canary",
    ):
        assert canary not in serialized_diagnostics


async def _exercise_event_sink_failure() -> None:
    def unavailable_sink(_event: OperationalEvent) -> None:
        raise RuntimeError("operational-event-sink-canary")

    server = create_research_agent_mcp_server(
        lambda _context: _registry(),
        event_sink=unavailable_sink,
        monotonic_ns=lambda: 0,
        subject_factory=lambda _context: "local_operator",
        trace_id_factory=lambda: "trace_sink_failure",
        transport="stdio",
    )
    async with Client(server) as client:
        result = await client.call_tool(
            "submit_research_run",
            _factor_command("event_sink_failure_request"),
        )

    assert result.is_error is False
    assert result.structured_content["outcome"] == "accepted"
    assert result.structured_content["run_id"] == "run_test"


async def _exercise_registry_factory_failure() -> None:
    events: list[OperationalEvent] = []

    def unavailable_registry(_context: object) -> ResearchAgentCapabilityRegistry:
        raise RuntimeError("registry-private-credential-canary")

    server = create_research_agent_mcp_server(
        unavailable_registry,
        event_sink=events.append,
        monotonic_ns=lambda: 0,
        subject_factory=lambda _context: "local_operator",
        trace_id_factory=lambda: "trace_registry_failure",
        transport="stdio",
    )
    async with Client(server) as client:
        result = await client.call_tool("get_research_context", {})

    assert result.is_error is True
    assert result.structured_content["code"] == "INTERNAL"
    assert result.structured_content["context"]["tool_name"] == "get_research_context"
    assert len(events) == 1
    assert events[0].context["outcome"] == "failed"
    assert events[0].context["failure_code"] == "INTERNAL"
    assert events[0].context["subject"] == "local_operator"
    assert events[0].level == "ERROR"
    assert "registry-private-credential-canary" not in (
        str(result.structured_content) + str(events)
    )


async def _exercise_safe_call_context() -> None:
    resource_canary = "postgresql://user:private-resource-canary@host/database"
    request_canary = "Bearer private-request-canary"
    formula_canary = "private-success-formula-canary"
    hypothesis_canary = "private-success-hypothesis-canary"
    events: list[OperationalEvent] = []
    async with Client(_server(_registry(), events=events)) as client:
        read = await client.call_tool(
            "get_research_run",
            {"run_id": resource_canary},
        )
        submitted = await client.call_tool(
            "submit_research_run",
            {
                **_factor_command(request_canary),
                "formula": formula_canary,
                "hypothesis": hypothesis_canary,
            },
        )
        invalid = await client.call_tool(
            "get_research_run",
            {"run_id": resource_canary, "credential": "private-credential-canary"},
        )
        spaced_request = await client.call_tool(
            "submit_research_run",
            {**_factor_command(" normalized-request "), "unexpected": True},
        )
        normalized_request = await client.call_tool(
            "submit_research_run",
            {**_factor_command("normalized-request"), "unexpected": True},
        )

    assert read.is_error is False
    assert submitted.is_error is False
    assert invalid.is_error is True
    assert invalid.structured_content["context"]["run_id"].startswith("run_id_")
    assert invalid.structured_content["context"]["tool_name"] == "get_research_run"
    assert spaced_request.structured_content["context"]["request_id"] == (
        normalized_request.structured_content["context"]["request_id"]
    )
    assert events[0].context["run_id"] == "run_test"
    assert events[1].context["request_id"].startswith("request_")
    assert events[1].context["run_id"] == "run_test"
    assert events[2].context["run_id"].startswith("run_id_")
    diagnostics = str(events) + str(invalid.structured_content)
    for canary in (
        resource_canary,
        request_canary,
        formula_canary,
        hypothesis_canary,
        "private-credential-canary",
    ):
        assert canary not in diagnostics


async def _exercise_surrogate_context() -> None:
    surrogate = "\ud800"
    for transport in ("stdio", "streamable_http"):
        registry = _registry()
        events: list[OperationalEvent] = []
        server = create_research_agent_mcp_server(
            lambda _context, selected=registry: selected,
            event_sink=events.append,
            monotonic_ns=lambda: 0,
            subject_factory=lambda _context: surrogate,
            trace_id_factory=lambda: "trace_surrogate",
            transport=transport,
        )
        async with Client(server) as client:
            result = await client.call_tool(
                "submit_research_run",
                {**_factor_command(surrogate), "unexpected": True},
            )

        assert result.is_error is True
        assert result.structured_content["code"] == "INVALID_INPUT"
        assert result.structured_content["context"]["request_id"].startswith("request_")
        assert len(events) == 1
        assert events[0].context["subject"].startswith(
            "stdio_" if transport == "stdio" else "oauth_"
        )
        assert events[0].context["request_id"].startswith("request_")


async def _exercise_transport_business_outcomes() -> None:
    for expected_code, build_case in (
        (
            "INVALID_INPUT",
            lambda: (_registry(), "get_research_run", {}),
        ),
        (
            "FORBIDDEN",
            lambda: (
                _registry(
                    ResearchAgentAuthority(
                        subject="denied",
                        researcher_id=TEST_RESEARCHER_ID,
                        scopes=frozenset(),
                    )
                ),
                "get_research_context",
                {},
            ),
        ),
        ("NOT_FOUND", _missing_run_case),
        ("STATE_CONFLICT", _result_state_conflict_case),
        ("IDEMPOTENCY_CONFLICT", _cancel_idempotency_conflict_case),
        ("TEMPORARILY_UNAVAILABLE", _temporary_run_case),
        (
            "INTERNAL",
            lambda: (
                _registry(selected_alpha_language=_ExplodingAlphaLanguage()),
                "get_alpha_catalog",
                {},
            ),
        ),
    ):
        transport_results = []
        for transport in ("stdio", "streamable_http"):
            registry, tool_name, arguments = build_case()
            events: list[OperationalEvent] = []
            server = create_research_agent_mcp_server(
                lambda _context, selected=registry: selected,
                event_sink=events.append,
                monotonic_ns=lambda: 0,
                subject_factory=lambda _context, selected=registry: (
                    selected.authority.subject
                ),
                trace_id_factory=lambda: "trace_transport_parity",
                transport=transport,
            )
            async with Client(server) as client:
                result = await client.call_tool(tool_name, arguments)
            assert result.is_error is True
            assert result.structured_content["code"] == expected_code
            assert len(events) == 1
            assert events[0].context["failure_code"] == expected_code
            assert events[0].context["transport"] == transport
            expected_level = (
                "ERROR"
                if expected_code == "INTERNAL"
                else "WARNING"
                if expected_code == "TEMPORARILY_UNAVAILABLE"
                else "INFO"
            )
            assert events[0].level == expected_level
            transport_results.append(result.structured_content)
        assert transport_results[0] == transport_results[1]

    reader = _ResearchRunReader()
    reader.admission_outcome = ResearchRunAdmissionRejectedOutcome(
        issues=[
            ResearchRunAdmissionIssue(
                code="UNKNOWN_IDENTIFIER",
                field="formula",
                message="Unknown Alpha identifier",
            )
        ],
        replayed=False,
    )
    successful_outcomes = []
    for transport in ("stdio", "streamable_http"):
        server = create_research_agent_mcp_server(
            lambda _context: _registry(research_runs=reader),
            event_sink=lambda _event: None,
            monotonic_ns=lambda: 0,
            subject_factory=lambda _context: "local_operator",
            trace_id_factory=lambda: "trace_success_parity",
            transport=transport,
        )
        async with Client(server) as client:
            diagnostic = await client.call_tool(
                "diagnose_alpha_formula",
                {"source": "unknown_alpha + close"},
            )
            rejected = await client.call_tool(
                "submit_research_run",
                _factor_command("domain_rejection_parity"),
            )
        assert diagnostic.is_error is False
        assert diagnostic.structured_content["valid"] is False
        assert rejected.is_error is False
        assert rejected.structured_content["outcome"] == "rejected"
        successful_outcomes.append(
            (diagnostic.structured_content, rejected.structured_content)
        )
    assert successful_outcomes[0] == successful_outcomes[1]


def _missing_run_case():
    reader = _ResearchRunReader()
    reader.polling_detail = None
    return _registry(research_runs=reader), "get_research_run", {"run_id": "run_missing"}


def _result_state_conflict_case():
    reader = _ResearchRunReader()
    reader.failure = ResearchRunResultUnavailable("result unavailable")
    return (
        _registry(research_runs=reader),
        "get_research_run_result",
        {"run_id": "run_test", "section": "factor"},
    )


def _cancel_idempotency_conflict_case():
    reader = _ResearchRunReader()
    reader.failure = ResearchRunCancelIdempotencyConflict("request conflict")
    authority = ResearchAgentAuthority(
        subject="canceller",
        researcher_id=TEST_RESEARCHER_ID,
        scopes=frozenset({ResearchAgentScope.RESEARCH_CANCEL}),
    )
    return (
        _registry(authority, research_runs=reader),
        "cancel_research_run",
        {"run_id": "run_test", "request_id": "cancel_conflict"},
    )


def _temporary_run_case():
    reader = _ResearchRunReader()
    reader.failure = ResearchRunTemporarilyUnavailable("database unavailable")
    return _registry(research_runs=reader), "list_research_runs", {}


async def _exercise_wire_response_ceiling() -> None:
    canary = "wire-response-canary-"
    events: list[OperationalEvent] = []
    async with Client(
        _server(
            _registry(selected_alpha_language=_OversizedAlphaLanguage()),
            events=events,
        )
    ) as client:
        result = await client.call_tool("get_alpha_catalog", {})

    assert result.is_error is True
    assert result.structured_content["code"] == "INTERNAL"
    serialized = result.model_dump_json(by_alias=True, exclude_none=True)
    assert len(serialized.encode()) < RESEARCH_AGENT_MAX_WIRE_RESPONSE_BYTES
    assert canary not in serialized
    assert events[0].context["response_bytes"] < RESEARCH_AGENT_MAX_WIRE_RESPONSE_BYTES


async def _exercise_wire_request_ceiling() -> None:
    registry_calls = 0
    registry = _registry()

    def registry_factory(_context) -> ResearchAgentCapabilityRegistry:
        nonlocal registry_calls
        registry_calls += 1
        return registry

    server = create_research_agent_mcp_server(
        registry_factory,
        event_sink=lambda _event: None,
        monotonic_ns=lambda: 0,
        subject_factory=lambda _context: "request-boundary",
        trace_id_factory=lambda: "trace_request_boundary",
        transport="stdio",
    )
    async with Client(server) as client:
        result = await client.call_tool(
            "diagnose_alpha_formula",
            {"source": "request-size-canary" + "x" * RESEARCH_AGENT_MAX_WIRE_REQUEST_BYTES},
        )

    assert result.is_error is True
    assert result.structured_content["code"] == "INVALID_INPUT"
    assert registry_calls == 0
    assert "request-size-canary" not in result.model_dump_json()


async def _exercise_principal_rate_limit() -> None:
    selected_subject = "principal-a"
    registry = _registry()
    server = create_research_agent_mcp_server(
        lambda _context: registry,
        event_sink=lambda _event: None,
        monotonic_ns=lambda: 0,
        subject_factory=lambda _context: selected_subject,
        trace_id_factory=lambda: "trace_rate_limit",
        transport="stdio",
    )
    async with Client(server) as client:
        for _ in range(RESEARCH_AGENT_MAX_CALLS_PER_WINDOW):
            assert (await client.call_tool("get_research_context", {})).is_error is False
        limited = await client.call_tool("get_research_context", {})
        selected_subject = "principal-b"
        independent = await client.call_tool("get_research_context", {})

    assert limited.is_error is True
    assert limited.structured_content["code"] == "TEMPORARILY_UNAVAILABLE"
    assert limited.structured_content["retry_after_seconds"] == 60
    assert independent.is_error is False


async def _exercise_principal_concurrency_limit() -> None:
    reader = _ConcurrentDataOverviewReader()
    registry = _registry(data_overview=reader)
    results = []
    async with Client(_server(registry, events=[])) as client:
        async with anyio.create_task_group() as tasks:
            for _ in range(RESEARCH_AGENT_MAX_CONCURRENT_CALLS):
                tasks.start_soon(_collect_context_result, client, results)
            with anyio.fail_after(2):
                while reader.started < RESEARCH_AGENT_MAX_CONCURRENT_CALLS:
                    await anyio.sleep(0)
            limited = await client.call_tool("get_research_context", {})
            reader.release.set()

    assert limited.is_error is True
    assert limited.structured_content["code"] == "TEMPORARILY_UNAVAILABLE"
    assert limited.structured_content["retry_after_seconds"] == 1
    assert len(results) == RESEARCH_AGENT_MAX_CONCURRENT_CALLS
    assert all(result.is_error is False for result in results)


async def _exercise_concurrency_across_rate_window() -> None:
    now = 0
    reader = _ConcurrentDataOverviewReader()
    registry = _registry(data_overview=reader)
    trace_ids = count()
    server = create_research_agent_mcp_server(
        lambda _context: registry,
        event_sink=lambda _event: None,
        monotonic_ns=lambda: now,
        subject_factory=lambda _context: "window-principal",
        trace_id_factory=lambda: f"trace_window_{next(trace_ids)}",
        transport="stdio",
    )
    results = []
    async with Client(server) as client:
        async with anyio.create_task_group() as tasks:
            for _ in range(RESEARCH_AGENT_MAX_CONCURRENT_CALLS):
                tasks.start_soon(_collect_context_result, client, results)
            with anyio.fail_after(2):
                while reader.started < RESEARCH_AGENT_MAX_CONCURRENT_CALLS:
                    await anyio.sleep(0)
            now = (RESEARCH_AGENT_RATE_WINDOW_SECONDS + 1) * 1_000_000_000
            limited = await client.call_tool("get_research_context", {})
            reader.release.set()
        admitted_after_release = await client.call_tool("get_research_context", {})

    assert limited.is_error is True
    assert limited.structured_content["code"] == "TEMPORARILY_UNAVAILABLE"
    assert admitted_after_release.is_error is False
    assert len(results) == RESEARCH_AGENT_MAX_CONCURRENT_CALLS


async def _exercise_cancelled_calls_release_concurrency() -> None:
    reader = _ConcurrentDataOverviewReader()
    events: list[OperationalEvent] = []
    scopes: list[anyio.CancelScope] = []
    async with Client(_server(_registry(data_overview=reader), events=events)) as client:
        async with anyio.create_task_group() as tasks:
            for _ in range(RESEARCH_AGENT_MAX_CONCURRENT_CALLS):
                tasks.start_soon(_call_context_until_cancelled, client, scopes)
            with anyio.fail_after(2):
                while (
                    reader.started < RESEARCH_AGENT_MAX_CONCURRENT_CALLS
                    or len(scopes) < RESEARCH_AGENT_MAX_CONCURRENT_CALLS
                ):
                    await anyio.sleep(0)
            for scope in scopes:
                scope.cancel()
            reader.release.set()
        admitted_after_cancel = await client.call_tool("get_research_context", {})

    assert admitted_after_cancel.is_error is False
    assert len(events) == RESEARCH_AGENT_MAX_CONCURRENT_CALLS + 1
    assert sum(event.context["outcome"] == "cancelled" for event in events) == (
        RESEARCH_AGENT_MAX_CONCURRENT_CALLS
    )


async def _exercise_stale_discovery_authority() -> None:
    current = {"registry": _registry()}
    trace_ids = count()
    server = create_research_agent_mcp_server(
        lambda _context: current["registry"],
        event_sink=lambda _event: None,
        monotonic_ns=lambda: 0,
        subject_factory=lambda _context: current["registry"].authority.subject,
        trace_id_factory=lambda: f"trace_test_{next(trace_ids)}",
        transport="stdio",
    )
    async with Client(server) as client:
        discovered = await client.list_tools()
        assert "get_research_context" in {tool.name for tool in discovered.tools}

        current["registry"] = _registry(
            ResearchAgentAuthority(
                subject="reader",
                researcher_id=TEST_RESEARCHER_ID,
                scopes=frozenset(),
            )
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
            researcher_id=TEST_RESEARCHER_ID,
            scopes=frozenset({ResearchAgentScope.RESEARCH_READ}),
        )
    )
    trace_ids = count()
    server = create_research_agent_mcp_server(
        lambda _context: registry,
        event_sink=events.append,
        monotonic_ns=lambda: 0,
        subject_factory=lambda _context: registry.authority.subject,
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
    assert len(events) == 1
    assert events[0].context["outcome"] == "cancelled"
    assert events[0].context["response_bytes"] == 0
    assert events[0].level == "INFO"


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
        subject_factory=lambda _context: registry.authority.subject,
        trace_id_factory=lambda: f"trace_test_{next(trace_ids)}",
        transport="stdio",
    )


def test_registry_conditional_signal_diagnostics_and_catalog() -> None:
    registry = _registry()
    catalog = registry.get_alpha_catalog(identifiers=["if_else"])
    assert [item.identifier for item in catalog.builtins] == ["if_else"]
    for source, valid in (
        ("if_else(close > open or close == 0, close, open)", True),
        ("if_else(close, close, open)", False),
        ("if_else(close > open, close, ts_mean(open, 253))", False),
    ):
        diagnostic = registry.diagnose_alpha_formula(source)
        assert diagnostic == alpha_language.diagnose(source)
        assert diagnostic.valid is valid


def test_registry_common_inputs_share_formal_industry_choices_and_diagnostics():
    registry = _registry()
    catalog = registry.get_alpha_catalog(identifiers=["industry_return", "universe_return"])
    assert catalog.industries == alpha_language.catalog().industries
    assert len(catalog.industries) == 31
    assert {item.identifier for item in catalog.builtins} == {"industry_return", "universe_return"}
    for source, valid in (
        ("close * industry_return(801010)", True),
        ("close * industry_return(801020)", False),
        ("close * industry_return(close)", False),
        ("close * universe_return(801010)", False),
    ):
        result = registry.diagnose_alpha_formula(source)
        assert result == alpha_language.diagnose(source)
        assert result.valid is valid
        if not valid:
            assert result.diagnostics[0].range.end.offset > result.diagnostics[0].range.start.offset


def test_registry_expression_diagnostics_apply_the_requested_context():
    registry = _registry()
    assert registry.diagnose_alpha_formula("0.7", context="exposure").valid
    assert registry.diagnose_alpha_formula(
        "if_else(universe_return() > 0, 1, 0.3)", context="exposure",
    ).valid
    assert not registry.diagnose_alpha_formula("0.7", context="signal").valid
    assert not registry.diagnose_alpha_formula("close", context="exposure").valid


def test_registry_whole_spec_diagnosis_is_read_only_and_uses_formal_validation():
    from thesistrace.research_run.service import ResearchRunService

    class NoPersistence:
        def __getattr__(self, name):
            raise AssertionError(f"Unexpected diagnosis persistence: {name}")

    service = ResearchRunService(
        NoPersistence(), compile_formula=alpha_language.compile, current_dataset=lambda: None,
    )
    registry = _registry(research_runs=service)
    capability = next(
        item for item in registry.accessible_capabilities() if item.name == "diagnose_research_spec"
    )
    assert capability.required_scope is ResearchAgentScope.RESEARCH_READ
    assert capability.annotations.read_only_hint is True
    assert capability.annotations.destructive_hint is False
    result = registry.invoke("diagnose_research_spec", {"spec": {
        "volatility_window": 20, "weighting": "equal_weight",
        "research_kind": "strategy_backtest", "formula": "close",
        "start_date": "2026-08-03", "end_date": "2026-08-05",
        "universe": "top300", "neutralization": "none", "initial_cash_cny": "100000",
        "holdings_count": 10, "selection_every_sessions": 5, "exposure_expression": "1.1",
    }}, trace_id="trace_spec_diagnosis")
    assert result.error is None
    assert result.result.valid is False
    assert result.result.issues[0].field == "exposure_expression"


@pytest.mark.parametrize("source,read_scope", [
    ({"kind": "research_run", "run_id": "run_test"}, ResearchAgentScope.RESEARCH_READ),
    ({"kind": "daily_track", "track_id": "track_test",
      "checkpoint_manifest_sha256": "a" * 64, "through_session": "2026-08-03"},
     ResearchAgentScope.TRACKING_READ),
])
def test_source_rerun_mcp_requires_source_read_authority(source, read_scope):
    async def exercise():
        for permitted in (False, True):
            scopes = {ResearchAgentScope.RESEARCH_EXECUTE}
            if permitted:
                scopes.add(read_scope)
            authority = ResearchAgentAuthority(
                subject="rerun-agent", researcher_id=TEST_RESEARCHER_ID,
                scopes=frozenset(scopes),
            )
            async with Client(_server(_registry(authority), events=[])) as client:
                result = await client.call_tool("submit_research_run", {
                    "request_id": "source-rerun", "folder_id": "folder_default",
                    "rerun_source": source,
                })
            assert result.is_error is not permitted
            if permitted:
                assert result.structured_content["outcome"] == "accepted"
            else:
                assert result.structured_content["code"] == "FORBIDDEN"
    anyio.run(exercise)
