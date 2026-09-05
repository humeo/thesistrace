from __future__ import annotations

import argparse
import re
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from time import perf_counter_ns
from typing import Literal
from uuid import UUID, uuid4

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response
from starlette.routing import Route

from thesistrace.alpha_language import alpha_language
from thesistrace.benchmark import (
    INTERNAL_STRATEGY_METRIC_PATH,
    InternalAnnualizedExcessRequest,
    InternalAnnualizedExcessResponse,
    StrategyComparisonError,
    StrategyComparisonFacts,
)
from thesistrace.daily_track import (
    DailyTrackDeleteConflict,
    DailyTrackDetail,
    DailyTrackDetailUnavailable,
    DailyTrackInvalidCursor,
    DailyTrackList,
    DailyTrackRefreshConflict,
    DailyTrackRefreshUnavailable,
    DailyTrackRetryConflict,
    DailyTrackRetryUnavailable,
    DailyTrackStopConflict,
    DailyTrackStopUnavailable,
    DailyTrackSummary,
    DailyTrackTemporarilyUnavailable,
    RefreshDailyTrackCommand,
    RetryDailyTrackCommand,
    StopDailyTrackCommand,
)
from thesistrace.data import (
    DataOverview,
    DataRefreshError,
    DataRefreshInvalidCursor,
    DatasetOperationalStatus,
    DatasetOperationalStatusService,
    DatasetOverviewService,
    RefreshOutcome,
    validate_financial_refresh_request,
    validate_industry_refresh_request,
    validate_market_refresh_request,
    validate_refresh_action_request,
)
from thesistrace.entrypoints.alpha_http import install_alpha_http
from thesistrace.entrypoints.authentication import (
    AuthSessionUnavailable,
    CoreAuthVerifier,
    CoreHttpSettings,
    InvalidLoginSession,
    InvalidOperatorProof,
    OperatorAccessNotFound,
    OperatorAuthorizer,
    SessionVerifier,
)
from thesistrace.entrypoints.runtime import CoreRuntime, CoreSettings, open_core_runtime
from thesistrace.operational_events import (
    OperationalEvent,
    OperationalEventWriter,
    emit_operational_event,
    sanitized_exception_context,
)
from thesistrace.research_agent import (
    ResearchAgentHTTPConfiguration,
    ResearchAgentModules,
    ResearchAgentProductionSettings,
    create_research_agent_http_transport,
)
from thesistrace.research_batch import (
    ResearchBatchAdmissionCommand,
    ResearchBatchAdmissionConflict,
    ResearchBatchAdmissionIssue,
    ResearchBatchAdmissionRejected,
    ResearchBatchAdmissionRejection,
    ResearchBatchCancelCommand,
    ResearchBatchCancelConflict,
    ResearchBatchDetail,
    ResearchBatchInvalidCursor,
    ResearchBatchList,
    ResearchBatchTemporarilyUnavailable,
)
from thesistrace.research_folder import (
    CreateResearchFolder,
    RenameResearchFolder,
    ResearchFolderConflict,
    ResearchFolderList,
    ResearchFolderSummary,
)
from thesistrace.research_run import (
    OrganizeResearchRunCommand,
    ResearchKind,
    ResearchRunAdmissionCommand,
    ResearchRunAdmissionConflict,
    ResearchRunAdmissionRejected,
    ResearchRunAdmissionRejection,
    ResearchRunCancelCommand,
    ResearchRunCancelConflict,
    ResearchRunDeleteConflict,
    ResearchRunDetail,
    ResearchRunInvalidCursor,
    ResearchRunList,
    ResearchRunOrganizationConflict,
    ResearchRunResultUnavailable,
    ResearchRunStartTrackingConflict,
    ResearchRunSummary,
    ResearchRunTemporarilyUnavailable,
    ResearchRunTrackingTemporarilyUnavailable,
    ResearchRunTrackingUnavailable,
    StartTrackingCommand,
)
from thesistrace.researcher import ResearcherBootstrapResult, ResearcherIdentity

_HEALTH_PATHS = frozenset({"/health/live", "/health/ready"})
_JSON_CONTENT_TYPE = re.compile(
    r"""^\s*application/json\s*(?:;\s*[!#$%&'*+\-.^_`|~0-9A-Za-z]+\s*=\s*(?:[!#$%&'*+\-.^_`|~0-9A-Za-z]+|"(?:[^"\\\r\n]|\\.)*"))*\s*$""",
    re.ASCII | re.IGNORECASE,
)


class MarketRefreshSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    as_of: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=512)
    proof: str = Field(min_length=80, max_length=80)


class MarketRefreshOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    as_of: datetime
    attempt_count: int = Field(ge=0)
    data_through_session: str | None
    failure_code: str | None
    idempotency_key: str
    kind: Literal["market"]
    last_failure_code: str | None
    last_refresh_at: datetime | None
    outcome: Literal["published", "no_change"] | None
    status: Literal["accepted", "running", "succeeded", "failed"]


class FinancialRefreshSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    idempotency_key: str = Field(min_length=1, max_length=512)
    observation_through_session: str = Field(min_length=10, max_length=10)
    proof: str = Field(min_length=80, max_length=80)


class FinancialRefreshOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    accepted_instrument_count: int | None = Field(default=None, ge=0)
    attempt_count: int = Field(ge=0)
    checked_no_structured_change_count: int | None = Field(default=None, ge=0)
    data_through_session: str | None
    discovery_gap_count: int | None = Field(default=None, ge=0)
    failed_instrument_count: int | None = Field(default=None, ge=0)
    failure_code: str | None
    financial_complete_through_session: str | None
    idempotency_key: str
    kind: Literal["financial"]
    last_failure_code: str | None
    last_refresh_at: datetime | None
    matched_trigger_count: int | None = Field(default=None, ge=0)
    observation_through_session: str
    outcome: (
        Literal[
            "published",
            "no_change",
            "degraded",
            "business_rejected",
            "infrastructure_failed",
        ]
        | None
    )
    pending_instrument_count: int | None = Field(default=None, ge=0)
    status: Literal["accepted", "running", "succeeded", "failed"]


class IndustryRefreshSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    idempotency_key: str = Field(min_length=1, max_length=512)
    observation_through_session: str = Field(min_length=10, max_length=10)
    proof: str = Field(min_length=80, max_length=80)


class IndustryRefreshOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt_count: int = Field(ge=0)
    data_through_session: str | None
    failure_code: str | None
    idempotency_key: str
    kind: Literal["industry"]
    last_failure_code: str | None
    last_refresh_at: datetime | None
    observation_through_session: str
    outcome: (
        Literal[
            "published",
            "no_change",
            "business_rejected",
            "infrastructure_failed",
        ]
        | None
    )
    status: Literal["accepted", "running", "succeeded", "failed"]


DataRefreshKind = Literal["market", "financial", "industry"]


class DataRefreshCancelCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: DataRefreshKind
    proof: str = Field(min_length=80, max_length=80)
    source_idempotency_key: str = Field(min_length=1, max_length=512)
    target: str = Field(min_length=1, max_length=128)


class DataRefreshRetryCommand(DataRefreshCancelCommand):
    new_idempotency_key: str = Field(min_length=1, max_length=512)


class DataRefreshActionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    as_of: datetime | None
    idempotency_key: str
    kind: DataRefreshKind
    observation_through_session: str | None
    status: Literal["accepted", "cancelled"]


def create_app(
    settings: CoreSettings | None = None,
    *,
    auth_verifier: SessionVerifier | None = None,
    operator_authorizer: OperatorAuthorizer | None = None,
    event_sink: OperationalEventWriter | None = None,
    http_request_id_factory: Callable[[], str] | None = None,
    monotonic_ns: Callable[[], int] | None = None,
    public_origin: str | None = None,
    enable_research_agent_http: bool = False,
    research_agent_http: ResearchAgentHTTPConfiguration | None = None,
) -> FastAPI:
    if enable_research_agent_http != (research_agent_http is not None):
        raise ValueError(
            "Research Agent HTTP must be explicitly enabled with a token verifier configuration"
        )
    selected_event_sink = emit_operational_event if event_sink is None else event_sink
    selected_request_id_factory = (
        _new_http_request_id if http_request_id_factory is None else http_request_id_factory
    )
    selected_monotonic_ns = perf_counter_ns if monotonic_ns is None else monotonic_ns

    research_agent_transport = None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        selected_settings = settings or CoreSettings.from_environment()
        http_settings: CoreHttpSettings | None = None
        selected_verifier = auth_verifier
        selected_operator_authorizer = operator_authorizer
        selected_public_origin = public_origin
        owned_verifier: CoreAuthVerifier | None = None
        if selected_verifier is None or selected_public_origin is None:
            http_settings = CoreHttpSettings.from_environment()
        if selected_verifier is None:
            assert http_settings is not None
            owned_verifier = CoreAuthVerifier(http_settings.auth_internal_origin)
            selected_verifier = owned_verifier
        if selected_operator_authorizer is None and isinstance(
            selected_verifier,
            CoreAuthVerifier,
        ):
            selected_operator_authorizer = selected_verifier
        if selected_public_origin is None:
            assert http_settings is not None
            selected_public_origin = http_settings.public_origin
        app.state.auth_verifier = selected_verifier
        app.state.operator_authorizer = selected_operator_authorizer
        app.state.public_origin = selected_public_origin
        try:
            with open_core_runtime(
                selected_settings,
                auth_readiness_origin=(
                    None if http_settings is None else http_settings.auth_internal_origin
                ),
            ) as runtime:
                app.state.core_runtime = runtime
                if research_agent_transport is None:
                    yield
                else:
                    async with research_agent_transport.session_manager.run():
                        yield
        finally:
            if owned_verifier is not None:
                await owned_verifier.aclose()

    app = FastAPI(title="ThesisTrace Core", lifespan=lifespan)
    if auth_verifier is not None:
        app.state.auth_verifier = auth_verifier
    if operator_authorizer is not None:
        app.state.operator_authorizer = operator_authorizer
    if public_origin is not None:
        app.state.public_origin = public_origin

    @app.middleware("http")
    async def authenticate_api_request(request: Request, call_next):  # type: ignore[no-untyped-def]
        if not request.url.path.startswith("/api/"):
            return await call_next(request)
        expected_origin = getattr(request.app.state, "public_origin", None)
        if not isinstance(expected_origin, str):
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"detail": "Authentication unavailable"},
            )
        if request.url.path.startswith("/api/operator/"):
            authorizer = _operator_authorizer(request)
            if authorizer is None:
                return _auth_unavailable_response()
            try:
                await authorizer.authorize_operator(request.headers.get("cookie"))
            except OperatorAccessNotFound:
                return Response(status_code=status.HTTP_404_NOT_FOUND)
            except AuthSessionUnavailable:
                return _auth_unavailable_response()
        else:
            verifier = getattr(request.app.state, "auth_verifier", None)
            if verifier is None:
                return JSONResponse(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    content={"detail": "Authentication unavailable"},
                )
            try:
                researcher = await verifier.verify(request.headers.get("cookie"))
            except InvalidLoginSession:
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "Authentication required"},
                )
            except AuthSessionUnavailable:
                return JSONResponse(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    content={"detail": "Authentication unavailable"},
                )
            request.state.researcher = researcher
        if request.method in {"POST", "PATCH", "DELETE"}:
            if request.headers.get("origin") != expected_origin:
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": "Origin not allowed"},
                )
            if _request_has_body(request) and not _request_is_json(request):
                return JSONResponse(
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    content={"detail": "JSON request required"},
                )
        return await call_next(request)

    if research_agent_http is not None:

        def research_agent_modules() -> ResearchAgentModules:
            runtime = app.state.core_runtime
            return ResearchAgentModules(
                data_overview=runtime.data_overview,
                research_folders=runtime.research_folders,
                alpha_language=alpha_language,
                research_authoring=runtime.research_authoring,
                research_runs=runtime.research_runs,
                research_batches=runtime.research_batches,
                daily_tracks=runtime.daily_tracks,
            )

        research_agent_transport = create_research_agent_http_transport(
            research_agent_http,
            modules=research_agent_modules,
            event_sink=selected_event_sink,
            monotonic_ns=selected_monotonic_ns,
        )
        app.router.routes.extend(research_agent_transport.metadata_routes)
        app.router.routes.append(
            Route(
                "/mcp",
                endpoint=research_agent_transport.app,
                name="research_agent_mcp",
                include_in_schema=False,
            )
        )

    @app.middleware("http")
    async def observe_http_request(request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.url.path in _HEALTH_PATHS:
            return await call_next(request)

        http_request_id = _trusted_http_request_id(
            request.headers.get("x-request-id"),
            selected_request_id_factory,
        )
        started = selected_monotonic_ns()
        try:
            response = await call_next(request)
        except Exception as error:
            route = _normalized_route(request)
            selected_event_sink(
                OperationalEvent(
                    level="ERROR",
                    component="core_api",
                    event="http_request_failed",
                    context={
                        "http_request_id": http_request_id,
                        "method": request.method,
                        "route": route,
                        "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                        **sanitized_exception_context(error),
                    },
                )
            )
            response = PlainTextResponse(
                "Internal Server Error",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        response.headers["X-Request-ID"] = http_request_id
        selected_event_sink(
            OperationalEvent(
                level="INFO",
                component="core_api",
                event="http_request_completed",
                context={
                    "http_request_id": http_request_id,
                    "method": request.method,
                    "route": _normalized_route(request),
                    "status_code": response.status_code,
                    "duration_ms": (selected_monotonic_ns() - started) // 1_000_000,
                },
            )
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def admission_validation_error(
        request: Request,
        error: RequestValidationError,
    ):
        if request.url.path in {
            "/api/operator/data/refreshes/market",
            "/api/operator/data/refreshes/financial",
        }:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={"code": "OPERATOR_REQUEST_INVALID"},
            )
        if request.method == "POST" and request.url.path == "/api/research-batches":
            rejection = ResearchBatchAdmissionRejection(
                issues=_batch_admission_validation_issues(error)
            )
            return JSONResponse(
                status_code=422,
                content=rejection.model_dump(mode="json"),
            )
        return await request_validation_exception_handler(request, error)

    install_alpha_http(
        app,
        financial_authoring_ready=lambda request: (
            _data_overview(request).overview().financial_research_readiness != "not_ready"
        ),
    )

    @app.get("/health/live", include_in_schema=False)
    def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", include_in_schema=False)
    def readiness(request: Request) -> JSONResponse:
        snapshot = _runtime(request).readiness.snapshot()
        return JSONResponse(
            status_code=(
                status.HTTP_200_OK
                if snapshot["status"] == "ready"
                else status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            content=snapshot,
        )

    @app.post(
        INTERNAL_STRATEGY_METRIC_PATH,
        response_model=InternalAnnualizedExcessResponse,
        include_in_schema=False,
    )
    def calculate_annualized_excess(
        request: Request,
        facts: InternalAnnualizedExcessRequest,
    ) -> InternalAnnualizedExcessResponse:
        try:
            metric = _runtime(request).annualized_excess_calculator.annualized_excess_return(
                StrategyComparisonFacts(
                    entry_session=facts.entry_session,
                    terminal_session=facts.terminal_session,
                    session_interval_count=facts.session_interval_count,
                    initial_cash_cny=facts.initial_cash_cny,
                    terminal_net_nav=facts.terminal_net_nav,
                )
            )
        except StrategyComparisonError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return InternalAnnualizedExcessResponse(
            annualized_excess_return=metric,
        )

    @app.get("/api/data", response_model=DataOverview)
    def data_overview(request: Request) -> DataOverview:
        return _data_overview(request).overview()

    @app.get(
        "/api/operator/data/status",
        response_model=DatasetOperationalStatus,
    )
    def operator_data_status(
        request: Request,
        cursor: str | None = None,
    ) -> DatasetOperationalStatus | Response:
        try:
            return _data_operational_status(request).status(cursor=cursor)
        except DataRefreshInvalidCursor:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"code": "DATA_REFRESH_CURSOR_INVALID"},
            )

    @app.post(
        "/api/operator/data/refreshes/cancel",
        response_model=DataRefreshActionReceipt,
    )
    async def cancel_data_refresh(
        request: Request,
        command: DataRefreshCancelCommand,
    ) -> DataRefreshActionReceipt | Response:
        try:
            source_key, _ = validate_refresh_action_request(
                source_idempotency_key=command.source_idempotency_key,
                kind=command.kind,
                target=command.target,
            )
        except DataRefreshError:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={"code": "OPERATOR_REQUEST_INVALID"},
            )
        authorizer = _operator_authorizer(request)
        if authorizer is None:
            return _auth_unavailable_response()
        try:
            await authorizer.consume_data_refresh_cancel_proof(
                request.headers.get("cookie"),
                idempotency_key=source_key,
                kind=command.kind,
                proof=command.proof,
                target=command.target,
            )
        except OperatorAccessNotFound:
            return Response(status_code=status.HTTP_404_NOT_FOUND)
        except InvalidOperatorProof:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"code": "OPERATOR_PROOF_INVALID"},
            )
        except AuthSessionUnavailable:
            return _auth_unavailable_response()
        try:
            outcome = await run_in_threadpool(
                _runtime(request).data_refreshes.cancel,
                idempotency_key=source_key,
                kind=command.kind,
                target=command.target,
            )
        except DataRefreshError as error:
            return _data_refresh_action_error(error)
        return _data_refresh_action_receipt(outcome)

    @app.post(
        "/api/operator/data/refreshes/retry",
        response_model=DataRefreshActionReceipt,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def retry_data_refresh(
        request: Request,
        command: DataRefreshRetryCommand,
    ) -> DataRefreshActionReceipt | Response:
        try:
            source_key, new_key = validate_refresh_action_request(
                source_idempotency_key=command.source_idempotency_key,
                kind=command.kind,
                target=command.target,
                new_idempotency_key=command.new_idempotency_key,
            )
        except DataRefreshError:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={"code": "OPERATOR_REQUEST_INVALID"},
            )
        assert new_key is not None
        authorizer = _operator_authorizer(request)
        if authorizer is None:
            return _auth_unavailable_response()
        try:
            await authorizer.consume_data_refresh_retry_proof(
                request.headers.get("cookie"),
                idempotency_key=source_key,
                kind=command.kind,
                new_idempotency_key=new_key,
                proof=command.proof,
                target=command.target,
            )
        except OperatorAccessNotFound:
            return Response(status_code=status.HTTP_404_NOT_FOUND)
        except InvalidOperatorProof:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"code": "OPERATOR_PROOF_INVALID"},
            )
        except AuthSessionUnavailable:
            return _auth_unavailable_response()
        try:
            outcome = await run_in_threadpool(
                _runtime(request).data_refreshes.retry,
                source_idempotency_key=source_key,
                idempotency_key=new_key,
                kind=command.kind,
                target=command.target,
            )
        except DataRefreshError as error:
            return _data_refresh_action_error(error)
        return _data_refresh_action_receipt(outcome)

    @app.post(
        "/api/operator/data/refreshes/market",
        response_model=MarketRefreshOperation,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def submit_market_refresh(
        request: Request,
        command: MarketRefreshSubmission,
    ) -> MarketRefreshOperation | Response:
        try:
            idempotency_key, as_of = validate_market_refresh_request(
                idempotency_key=command.idempotency_key,
                as_of=command.as_of,
            )
        except DataRefreshError:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={"code": "OPERATOR_REQUEST_INVALID"},
            )
        authorizer = _operator_authorizer(request)
        if authorizer is None:
            return _auth_unavailable_response()
        try:
            await authorizer.consume_market_refresh_proof(
                request.headers.get("cookie"),
                as_of=command.as_of,
                idempotency_key=idempotency_key,
                proof=command.proof,
            )
        except OperatorAccessNotFound:
            return Response(status_code=status.HTTP_404_NOT_FOUND)
        except InvalidOperatorProof:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"code": "OPERATOR_PROOF_INVALID"},
            )
        except AuthSessionUnavailable:
            return _auth_unavailable_response()
        try:
            outcome = await run_in_threadpool(
                _runtime(request).data_refreshes.submit,
                idempotency_key=idempotency_key,
                as_of=as_of,
            )
        except DataRefreshError as error:
            if error.code == "IDEMPOTENCY_KEY_CONFLICT":
                return JSONResponse(
                    status_code=status.HTTP_409_CONFLICT,
                    content={"code": error.code},
                )
            if error.code == "DATA_NOT_READY":
                return JSONResponse(
                    status_code=status.HTTP_409_CONFLICT,
                    content={"code": error.code},
                )
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={"code": "OPERATOR_REQUEST_INVALID"},
            )
        return _market_refresh_operation(outcome)

    @app.get(
        "/api/operator/data/refreshes/market",
        response_model=MarketRefreshOperation,
    )
    def inspect_market_refresh(
        request: Request,
        idempotency_key: str = Query(min_length=1, max_length=512),
        as_of: str = Query(min_length=1, max_length=128),
    ) -> MarketRefreshOperation | Response:
        try:
            normalized_key, normalized_as_of = validate_market_refresh_request(
                idempotency_key=idempotency_key,
                as_of=as_of,
            )
            outcome = _runtime(request).data_refreshes.inspect(normalized_key)
        except DataRefreshError as error:
            if error.code == "REFRESH_NOT_FOUND":
                return Response(status_code=status.HTTP_404_NOT_FOUND)
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={"code": "OPERATOR_REQUEST_INVALID"},
            )
        if outcome.as_of != normalized_as_of.isoformat():
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={"code": "IDEMPOTENCY_KEY_CONFLICT"},
            )
        return _market_refresh_operation(outcome)

    @app.post(
        "/api/operator/data/refreshes/financial",
        response_model=FinancialRefreshOperation,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def submit_financial_refresh(
        request: Request,
        command: FinancialRefreshSubmission,
    ) -> FinancialRefreshOperation | Response:
        try:
            idempotency_key, target = validate_financial_refresh_request(
                idempotency_key=command.idempotency_key,
                observation_through_session=command.observation_through_session,
            )
        except DataRefreshError:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={"code": "OPERATOR_REQUEST_INVALID"},
            )
        authorizer = _operator_authorizer(request)
        if authorizer is None:
            return _auth_unavailable_response()
        try:
            await authorizer.consume_financial_refresh_proof(
                request.headers.get("cookie"),
                idempotency_key=idempotency_key,
                observation_through_session=command.observation_through_session,
                proof=command.proof,
            )
        except OperatorAccessNotFound:
            return Response(status_code=status.HTTP_404_NOT_FOUND)
        except InvalidOperatorProof:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"code": "OPERATOR_PROOF_INVALID"},
            )
        except AuthSessionUnavailable:
            return _auth_unavailable_response()
        try:
            outcome = await run_in_threadpool(
                _runtime(request).data_refreshes.submit_financial,
                idempotency_key=idempotency_key,
                observation_through_session=target,
            )
        except DataRefreshError as error:
            if error.code in {"IDEMPOTENCY_KEY_CONFLICT", "DATA_NOT_READY"}:
                return JSONResponse(
                    status_code=status.HTTP_409_CONFLICT,
                    content={"code": error.code},
                )
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={"code": "OPERATOR_REQUEST_INVALID"},
            )
        return _financial_refresh_operation(outcome)

    @app.get(
        "/api/operator/data/refreshes/financial",
        response_model=FinancialRefreshOperation,
    )
    def inspect_financial_refresh(
        request: Request,
        idempotency_key: str = Query(min_length=1, max_length=512),
        observation_through_session: str = Query(min_length=10, max_length=10),
    ) -> FinancialRefreshOperation | Response:
        try:
            normalized_key, target = validate_financial_refresh_request(
                idempotency_key=idempotency_key,
                observation_through_session=observation_through_session,
            )
            outcome = _runtime(request).data_refreshes.inspect(normalized_key)
        except DataRefreshError as error:
            if error.code == "REFRESH_NOT_FOUND":
                return Response(status_code=status.HTTP_404_NOT_FOUND)
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={"code": "OPERATOR_REQUEST_INVALID"},
            )
        if outcome.kind != "financial" or outcome.observation_through_session != target:
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={"code": "IDEMPOTENCY_KEY_CONFLICT"},
            )
        return _financial_refresh_operation(outcome)

    @app.post(
        "/api/operator/data/refreshes/industry",
        response_model=IndustryRefreshOperation,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def submit_industry_refresh(
        request: Request,
        command: IndustryRefreshSubmission,
    ) -> IndustryRefreshOperation | Response:
        try:
            idempotency_key, target = validate_industry_refresh_request(
                idempotency_key=command.idempotency_key,
                observation_through_session=command.observation_through_session,
            )
        except DataRefreshError:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={"code": "OPERATOR_REQUEST_INVALID"},
            )
        authorizer = _operator_authorizer(request)
        if authorizer is None:
            return _auth_unavailable_response()
        try:
            await authorizer.consume_industry_refresh_proof(
                request.headers.get("cookie"),
                idempotency_key=idempotency_key,
                observation_through_session=command.observation_through_session,
                proof=command.proof,
            )
        except OperatorAccessNotFound:
            return Response(status_code=status.HTTP_404_NOT_FOUND)
        except InvalidOperatorProof:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"code": "OPERATOR_PROOF_INVALID"},
            )
        except AuthSessionUnavailable:
            return _auth_unavailable_response()
        try:
            outcome = await run_in_threadpool(
                _runtime(request).data_refreshes.submit_industry,
                idempotency_key=idempotency_key,
                observation_through_session=target,
            )
        except DataRefreshError as error:
            if error.code in {"IDEMPOTENCY_KEY_CONFLICT", "DATA_NOT_READY"}:
                return JSONResponse(
                    status_code=status.HTTP_409_CONFLICT,
                    content={"code": error.code},
                )
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={"code": "OPERATOR_REQUEST_INVALID"},
            )
        return _industry_refresh_operation(outcome)

    @app.get(
        "/api/operator/data/refreshes/industry",
        response_model=IndustryRefreshOperation,
    )
    def inspect_industry_refresh(
        request: Request,
        idempotency_key: str = Query(min_length=1, max_length=512),
        observation_through_session: str = Query(min_length=10, max_length=10),
    ) -> IndustryRefreshOperation | Response:
        try:
            normalized_key, target = validate_industry_refresh_request(
                idempotency_key=idempotency_key,
                observation_through_session=observation_through_session,
            )
            outcome = _runtime(request).data_refreshes.inspect(normalized_key)
        except DataRefreshError as error:
            if error.code == "REFRESH_NOT_FOUND":
                return Response(status_code=status.HTTP_404_NOT_FOUND)
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={"code": "OPERATOR_REQUEST_INVALID"},
            )
        if outcome.kind != "industry" or outcome.observation_through_session != target:
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={"code": "IDEMPOTENCY_KEY_CONFLICT"},
            )
        return _industry_refresh_operation(outcome)

    @app.post(
        "/api/researcher/bootstrap",
        response_model=ResearcherBootstrapResult,
    )
    def bootstrap_researcher(request: Request) -> ResearcherBootstrapResult:
        return _runtime(request).researchers.bootstrap(_researcher(request))

    @app.get("/api/research-folders", response_model=ResearchFolderList)
    def list_research_folders(request: Request) -> ResearchFolderList:
        return _runtime(request).research_folders.list(_researcher_id(request))

    @app.post(
        "/api/research-folders",
        response_model=ResearchFolderSummary,
        status_code=status.HTTP_201_CREATED,
    )
    def create_research_folder(
        request: Request,
        command: CreateResearchFolder,
    ) -> ResearchFolderSummary:
        return _runtime(request).research_folders.create(_researcher_id(request), command)

    @app.patch(
        "/api/research-folders/{folder_id}",
        response_model=ResearchFolderSummary,
    )
    def rename_research_folder(
        request: Request,
        folder_id: str,
        command: RenameResearchFolder,
    ) -> ResearchFolderSummary:
        try:
            folder = _runtime(request).research_folders.rename(
                _researcher_id(request), folder_id, command
            )
        except ResearchFolderConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if folder is None:
            raise HTTPException(status_code=404, detail="Research Folder not found")
        return folder

    @app.delete(
        "/api/research-folders/{folder_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def delete_research_folder(request: Request, folder_id: str) -> None:
        try:
            deleted = _runtime(request).research_folders.delete(_researcher_id(request), folder_id)
        except ResearchFolderConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if not deleted:
            raise HTTPException(status_code=404, detail="Research Folder not found")

    @app.post(
        "/api/research-batches",
        response_model=ResearchBatchDetail,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def admit_research_batch(
        request: Request,
        command: ResearchBatchAdmissionCommand,
    ) -> ResearchBatchDetail | JSONResponse:
        try:
            return _runtime(request).research_batches.admit(_researcher_id(request), command)
        except ResearchBatchAdmissionConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ResearchBatchAdmissionRejected as error:
            rejection = ResearchBatchAdmissionRejection(issues=error.issues)
            return JSONResponse(
                status_code=422,
                content=rejection.model_dump(mode="json"),
            )
        except ResearchBatchTemporarilyUnavailable as error:
            raise HTTPException(
                status_code=503,
                detail="Research Batch admission is temporarily unavailable",
            ) from error

    @app.get("/api/research-batches", response_model=ResearchBatchList)
    def list_research_batches(
        request: Request,
        cursor: str | None = None,
        limit: int = Query(default=50, ge=1, le=100),
    ) -> ResearchBatchList:
        try:
            return _runtime(request).research_batches.list(
                _researcher_id(request), cursor=cursor, limit=limit
            )
        except ResearchBatchInvalidCursor as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except ResearchBatchTemporarilyUnavailable as error:
            raise HTTPException(
                status_code=503,
                detail="Research Batch listing is temporarily unavailable",
            ) from error

    @app.get(
        "/api/research-batches/{batch_id}",
        response_model=ResearchBatchDetail,
    )
    def get_research_batch(request: Request, batch_id: str) -> ResearchBatchDetail:
        try:
            batch = _runtime(request).research_batches.get(_researcher_id(request), batch_id)
        except ResearchBatchTemporarilyUnavailable as error:
            raise HTTPException(
                status_code=503,
                detail="Research Batch lookup is temporarily unavailable",
            ) from error
        if batch is None:
            raise HTTPException(status_code=404, detail="Research Batch not found")
        return batch

    @app.post(
        "/api/research-batches/{batch_id}/cancel",
        response_model=ResearchBatchDetail,
    )
    def cancel_research_batch(
        request: Request,
        batch_id: str,
        command: ResearchBatchCancelCommand,
    ) -> ResearchBatchDetail:
        try:
            batch = _runtime(request).research_batches.cancel(
                _researcher_id(request), batch_id, command
            )
        except ResearchBatchCancelConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ResearchBatchTemporarilyUnavailable as error:
            raise HTTPException(
                status_code=503,
                detail="Research Batch cancellation is temporarily unavailable",
            ) from error
        if batch is None:
            raise HTTPException(status_code=404, detail="Research Batch not found")
        return batch

    @app.post(
        "/api/research-runs",
        response_model=ResearchRunSummary,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def admit_research_run(
        request: Request,
        command: ResearchRunAdmissionCommand,
    ) -> ResearchRunSummary | JSONResponse:
        try:
            return _runtime(request).research_runs.admit(_researcher_id(request), command)
        except ResearchRunAdmissionConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ResearchRunAdmissionRejected as error:
            rejection = ResearchRunAdmissionRejection(issues=error.issues)
            return JSONResponse(
                status_code=422,
                content=rejection.model_dump(mode="json"),
            )
        except ResearchRunTemporarilyUnavailable as error:
            raise HTTPException(
                status_code=503,
                detail="ResearchRun admission temporarily unavailable",
            ) from error

    @app.get("/api/research-runs", response_model=ResearchRunList)
    def list_research_runs(
        request: Request,
        folder_id: str | None = None,
        research_kind: ResearchKind | None = None,
        cursor: str | None = None,
        limit: int = Query(default=50, ge=1, le=100),
    ) -> ResearchRunList:
        try:
            return _runtime(request).research_runs.list(
                _researcher_id(request),
                folder_id=folder_id,
                research_kind=research_kind,
                cursor=cursor,
                limit=limit,
            )
        except ResearchRunInvalidCursor as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except ResearchRunTemporarilyUnavailable as error:
            raise HTTPException(
                status_code=503,
                detail="ResearchRun history temporarily unavailable",
            ) from error

    @app.patch(
        "/api/research-runs/{run_id}",
        response_model=ResearchRunSummary,
    )
    def organize_research_run(
        request: Request,
        run_id: str,
        command: OrganizeResearchRunCommand,
    ) -> ResearchRunSummary:
        try:
            run = _runtime(request).research_runs.organize(_researcher_id(request), run_id, command)
        except ResearchRunOrganizationConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if run is None:
            raise HTTPException(status_code=404, detail="ResearchRun not found")
        return run

    @app.get(
        "/api/research-runs/{run_id}",
        response_model=ResearchRunDetail,
    )
    def get_research_run(request: Request, run_id: str) -> ResearchRunDetail:
        try:
            run = _runtime(request).research_runs.get_detail(_researcher_id(request), run_id)
        except ResearchRunResultUnavailable as error:
            raise HTTPException(
                status_code=503,
                detail="ResearchRun Result unavailable",
            ) from error
        if run is None:
            raise HTTPException(status_code=404, detail="ResearchRun not found")
        return run

    @app.delete(
        "/api/research-runs/{run_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def delete_research_run(request: Request, run_id: str) -> None:
        try:
            deleted = _runtime(request).research_runs.delete(_researcher_id(request), run_id)
        except ResearchRunDeleteConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if not deleted:
            raise HTTPException(status_code=404, detail="ResearchRun not found")

    @app.post(
        "/api/research-runs/{run_id}/cancel",
        response_model=ResearchRunSummary,
    )
    def cancel_research_run(
        request: Request,
        run_id: str,
        command: ResearchRunCancelCommand,
    ) -> ResearchRunSummary:
        try:
            outcome = _runtime(request).research_runs.cancel(
                _researcher_id(request), run_id, command
            )
        except ResearchRunCancelConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ResearchRunTemporarilyUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if outcome is None:
            raise HTTPException(status_code=404, detail="ResearchRun not found")
        return outcome.run

    @app.post(
        "/api/research-runs/{run_id}/daily-tracks",
        response_model=DailyTrackSummary,
        status_code=status.HTTP_201_CREATED,
    )
    def start_tracking(
        request: Request,
        run_id: str,
        command: StartTrackingCommand,
    ) -> DailyTrackSummary:
        try:
            track = _runtime(request).research_runs.start_tracking(
                _researcher_id(request), run_id, command
            )
        except ResearchRunStartTrackingConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ResearchRunTrackingUnavailable as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ResearchRunTrackingTemporarilyUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if track is None:
            raise HTTPException(status_code=404, detail="ResearchRun not found")
        return track

    @app.get("/api/daily-tracks", response_model=DailyTrackList)
    def list_daily_tracks(
        request: Request,
        cursor: str | None = Query(default=None, min_length=1, max_length=1024),
        limit: int = Query(default=20, ge=1, le=50),
    ) -> DailyTrackList:
        try:
            return _runtime(request).daily_tracks.list(
                _researcher_id(request),
                cursor=cursor,
                limit=limit,
            )
        except DailyTrackInvalidCursor as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except DailyTrackTemporarilyUnavailable as error:
            raise HTTPException(
                status_code=503,
                detail="DailyTrack listing is temporarily unavailable",
            ) from error

    @app.get("/api/daily-tracks/{track_id}", response_model=DailyTrackDetail)
    def get_daily_track(request: Request, track_id: str) -> DailyTrackDetail:
        try:
            track = _runtime(request).daily_tracks.get(_researcher_id(request), track_id)
        except DailyTrackDetailUnavailable as error:
            raise HTTPException(
                status_code=503,
                detail="DailyTrack detail is unavailable",
            ) from error
        if track is None:
            raise HTTPException(status_code=404, detail="DailyTrack not found")
        return track

    @app.delete(
        "/api/daily-tracks/{track_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def delete_daily_track(request: Request, track_id: str) -> None:
        try:
            deleted = _runtime(request).daily_tracks.delete(_researcher_id(request), track_id)
        except DailyTrackDeleteConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if not deleted:
            raise HTTPException(status_code=404, detail="DailyTrack not found")

    @app.post(
        "/api/daily-tracks/{track_id}/refresh",
        response_model=DailyTrackSummary,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def refresh_daily_track(
        request: Request,
        track_id: str,
        command: RefreshDailyTrackCommand,
    ) -> DailyTrackSummary:
        try:
            track = _runtime(request).daily_tracks.refresh(
                _researcher_id(request), track_id, command
            )
        except DailyTrackRefreshConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except DailyTrackRefreshUnavailable as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except DailyTrackTemporarilyUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if track is None:
            raise HTTPException(status_code=404, detail="DailyTrack not found")
        return track

    @app.post(
        "/api/daily-tracks/{track_id}/retry",
        response_model=DailyTrackSummary,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def retry_daily_track(
        request: Request,
        track_id: str,
        command: RetryDailyTrackCommand,
    ) -> DailyTrackSummary:
        try:
            track = _runtime(request).daily_tracks.retry(_researcher_id(request), track_id, command)
        except DailyTrackRetryConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except DailyTrackRetryUnavailable as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except DailyTrackTemporarilyUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if track is None:
            raise HTTPException(status_code=404, detail="DailyTrack not found")
        return track

    @app.post(
        "/api/daily-tracks/{track_id}/stop",
        response_model=DailyTrackSummary,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def stop_daily_track(
        request: Request,
        track_id: str,
        command: StopDailyTrackCommand,
    ) -> DailyTrackSummary:
        try:
            track = _runtime(request).daily_tracks.stop(_researcher_id(request), track_id, command)
        except DailyTrackStopConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except DailyTrackStopUnavailable as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except DailyTrackTemporarilyUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if track is None:
            raise HTTPException(status_code=404, detail="DailyTrack not found")
        return track

    return app


def _batch_admission_validation_issues(
    error: RequestValidationError,
) -> list[ResearchBatchAdmissionIssue]:
    body = error.body if isinstance(error.body, Mapping) else {}
    return [
        ResearchBatchAdmissionIssue(
            code="INVALID_BATCH_INPUT",
            field=_batch_validation_field(issue.get("loc", ())),
            item_key=_batch_validation_item_key(body, issue.get("loc", ())),
            message=str(issue.get("msg", "Research Batch input is invalid")),
        )
        for issue in error.errors()
    ]


def _batch_validation_field(location: object) -> str:
    components = _batch_validation_components(location)
    field = ""
    for component in components:
        if isinstance(component, int):
            field = f"{field}[{component}]"
        elif isinstance(component, str):
            field = f"{field}.{component}" if field else component
    return field or "batch"


def _batch_validation_item_key(
    body: Mapping[object, object],
    location: object,
) -> str | None:
    components = _batch_validation_components(location)
    for array_name in ("factors", "strategies"):
        if array_name not in components:
            continue
        position = components.index(array_name)
        ordinal = (
            components[position + 1]
            if position + 1 < len(components) and isinstance(components[position + 1], int)
            else 20
        )
        items = body.get(array_name)
        if not isinstance(items, list) or not 0 <= ordinal < len(items):
            return None
        item = items[ordinal]
        if not isinstance(item, Mapping):
            return None
        item_key = item.get("item_key")
        if not isinstance(item_key, str) or not item_key.strip():
            return None
        return item_key.strip()
    return None


def _batch_validation_components(location: object) -> list[str | int]:
    if not isinstance(location, Sequence) or isinstance(location, (str, bytes)):
        return []
    return [
        component
        for component in location
        if isinstance(component, (str, int))
        and component not in {"body", "factor_evaluation", "strategy_sweep"}
    ]


def _runtime(request: Request) -> CoreRuntime:
    return request.app.state.core_runtime


def _operator_authorizer(request: Request) -> OperatorAuthorizer | None:
    return getattr(request.app.state, "operator_authorizer", None)


def _auth_unavailable_response() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"code": "AUTH_SERVICE_UNAVAILABLE"},
    )


def _data_refresh_action_error(error: DataRefreshError) -> JSONResponse:
    if error.code == "REFRESH_NOT_FOUND":
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"code": error.code},
        )
    if error.code in {
        "IDEMPOTENCY_KEY_CONFLICT",
        "REFRESH_NOT_CANCELLABLE",
        "REFRESH_NOT_RETRYABLE",
        "REFRESH_TARGET_CONFLICT",
    }:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"code": error.code},
        )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"code": "OPERATOR_REQUEST_INVALID"},
    )


def _data_refresh_action_receipt(outcome: RefreshOutcome) -> DataRefreshActionReceipt:
    target_is_valid = (
        outcome.kind == "market"
        and outcome.as_of is not None
        and outcome.observation_through_session is None
    ) or (
        outcome.kind in {"financial", "industry"}
        and outcome.as_of is None
        and outcome.observation_through_session is not None
    )
    if (
        outcome.kind not in {"market", "financial", "industry"}
        or outcome.status not in {"accepted", "cancelled"}
        or not target_is_valid
    ):
        raise DataRefreshError("REFRESH_RECEIPT_INVALID")
    return DataRefreshActionReceipt(
        as_of=outcome.as_of,
        idempotency_key=outcome.idempotency_key,
        kind=outcome.kind,  # type: ignore[arg-type]
        observation_through_session=outcome.observation_through_session,
        status=outcome.status,  # type: ignore[arg-type]
    )


def _market_refresh_operation(outcome: RefreshOutcome) -> MarketRefreshOperation:
    return MarketRefreshOperation(
        as_of=outcome.as_of,
        attempt_count=outcome.attempt_count,
        data_through_session=outcome.data_through_session,
        failure_code=outcome.failure_code,
        idempotency_key=outcome.idempotency_key,
        kind="market",
        last_failure_code=outcome.last_failure_code,
        last_refresh_at=outcome.last_refresh_at,
        outcome=outcome.outcome,  # type: ignore[arg-type]
        status=outcome.status,  # type: ignore[arg-type]
    )


def _financial_refresh_operation(outcome: RefreshOutcome) -> FinancialRefreshOperation:
    if outcome.kind != "financial" or outcome.observation_through_session is None:
        raise DataRefreshError("REFRESH_RECEIPT_INVALID")
    return FinancialRefreshOperation(
        accepted_instrument_count=outcome.accepted_instrument_count,
        attempt_count=outcome.attempt_count,
        checked_no_structured_change_count=(outcome.checked_no_structured_change_count),
        data_through_session=outcome.data_through_session,
        discovery_gap_count=outcome.discovery_gap_count,
        failed_instrument_count=outcome.failed_instrument_count,
        failure_code=outcome.failure_code,
        financial_complete_through_session=(outcome.financial_complete_through_session),
        idempotency_key=outcome.idempotency_key,
        kind="financial",
        last_failure_code=outcome.last_failure_code,
        last_refresh_at=outcome.last_refresh_at,
        matched_trigger_count=outcome.matched_trigger_count,
        observation_through_session=outcome.observation_through_session,
        outcome=outcome.outcome,  # type: ignore[arg-type]
        pending_instrument_count=outcome.pending_instrument_count,
        status=outcome.status,  # type: ignore[arg-type]
    )


def _industry_refresh_operation(outcome: RefreshOutcome) -> IndustryRefreshOperation:
    if outcome.kind != "industry" or outcome.observation_through_session is None:
        raise DataRefreshError("REFRESH_RECEIPT_INVALID")
    return IndustryRefreshOperation(
        attempt_count=outcome.attempt_count,
        data_through_session=outcome.data_through_session,
        failure_code=outcome.failure_code,
        idempotency_key=outcome.idempotency_key,
        kind="industry",
        last_failure_code=outcome.last_failure_code,
        last_refresh_at=outcome.last_refresh_at,
        observation_through_session=outcome.observation_through_session,
        outcome=outcome.outcome,  # type: ignore[arg-type]
        status=outcome.status,  # type: ignore[arg-type]
    )


def _researcher(request: Request) -> ResearcherIdentity:
    return request.state.researcher


def _researcher_id(request: Request) -> UUID:
    return _researcher(request).researcher_id


def _request_has_body(request: Request) -> bool:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            return int(content_length) > 0
        except ValueError:
            return True
    return request.headers.get("transfer-encoding") is not None


def _request_is_json(request: Request) -> bool:
    return _JSON_CONTENT_TYPE.fullmatch(request.headers.get("content-type", "")) is not None


def _data_overview(request: Request) -> DatasetOverviewService:
    overview = _runtime(request).data_overview
    if overview is None:
        raise RuntimeError("Data Overview is unavailable outside the API runtime")
    return overview


def _data_operational_status(request: Request) -> DatasetOperationalStatusService:
    operational_status = _runtime(request).data_operational_status
    if operational_status is None:
        raise RuntimeError("Dataset operational status is unavailable outside the API runtime")
    return operational_status


def _normalized_route(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "unmatched"


def _new_http_request_id() -> str:
    return str(uuid4())


def _trusted_http_request_id(
    candidate: str | None,
    fallback: Callable[[], str],
) -> str:
    if candidate is not None:
        normalized = candidate.lower()
        try:
            parsed = UUID(normalized)
        except ValueError:
            parsed = None
        if parsed is not None and parsed.version is not None and str(parsed) == normalized:
            return normalized
    return fallback()


def create_production_app() -> FastAPI:
    research_agent = ResearchAgentProductionSettings.from_environment()
    from dataclasses import replace

    from thesistrace.research_agent.external_oauth import McpTokenVerifier

    configuration = research_agent.http_configuration()
    http_settings = CoreHttpSettings.from_environment()
    configuration = replace(configuration, token_verifier=McpTokenVerifier(
        internal=configuration.token_verifier,
        auth_origin=http_settings.auth_internal_origin,
        resource=research_agent.resource_server_url,
    ))
    return create_app(
        enable_research_agent_http=True,
        research_agent_http=configuration,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the canonical ThesisTrace Core HTTP adapter")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8100)
    arguments = parser.parse_args()
    uvicorn.run(
        create_production_app(),
        host=arguments.host,
        port=arguments.port,
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    main()
