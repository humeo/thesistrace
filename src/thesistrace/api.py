import copy
import os
from datetime import UTC, date, datetime

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from thesistrace.auth import (
    AuthenticationFailure,
    IdentityVerifier,
    build_identity_verifier,
)
from thesistrace.config import Settings, settings_from_environment
from thesistrace.datasets import DatasetPublisher, InvalidFixtureError
from thesistrace.definitions import DefinitionValidationError, ResearchDefinitionService
from thesistrace.hosted.observability import configure_observability, instrument_http
from thesistrace.management import SourceAuthorizationService, build_management_store
from thesistrace.objects import ImmutableObjectStore
from thesistrace.provisioning import (
    ProvisioningError,
    RegistrationService,
    build_registration_service,
)
from thesistrace.quota import QuotaExceededError
from thesistrace.rate_limits import ApiRateLimiter, RateLimitRejection
from thesistrace.research_runs import (
    ResearchRunService,
    recover_staged_research_run,
)
from thesistrace.resource_deletion import (
    ResourceDeletionError,
    ResourceDeletionService,
)
from thesistrace.runtime import RuntimePorts, build_runtime
from thesistrace.storage import DatasetPublicationConflict
from thesistrace.storage_admission import StorageAdmissionError
from thesistrace.tenancy import authenticated_subject, verified_subject
from thesistrace.tracking import (
    DailyTrackingError,
    DailyTrackingService,
    EquivalenceError,
)
from thesistrace.tracking_operations import TrackingOperationService
from thesistrace.tushare_source import (
    HttpTushareTransport,
    TushareAdapter,
    TushareSourceError,
    TushareTransport,
    normalize_tushare_increment,
    normalize_tushare_snapshot,
)


class BootstrapRequest(BaseModel):
    fixture: str


class LiveBootstrapRequest(BaseModel):
    as_of: date


class PriceCorrection(BaseModel):
    session: str
    instrument_id: str
    field: str
    value: str


class FixtureIncrementRequest(BaseModel):
    new_sessions: int
    corrections: list[PriceCorrection]


class KernelUpgradeRequest(BaseModel):
    calculation_kernel: str
    numeric_execution_contract: str


def error_detail(reason_code: str, message: str) -> dict[str, str]:
    return {"reason_code": reason_code, "message": message}


def quota_error_detail(error: QuotaExceededError) -> dict[str, object]:
    noun = {
        "max_active_daily_tracks": "DailyTrack",
        "max_nonterminal_user_compute_jobs": "Compute",
        "max_private_storage_bytes": "Storage",
    }.get(error.dimension, "Resource")
    return {
        "reason_code": error.reason_code,
        "message": f"Personal Workspace {noun} quota is full",
        "dimension": error.dimension,
        "limit": error.limit,
    }


def deletion_response(tombstone: dict[str, object]) -> JSONResponse:
    return JSONResponse(
        status_code=202,
        content={
            "resource_kind": tombstone["resource_kind"],
            "resource_id": tombstone["resource_id"],
            "deleted_at": tombstone["deleted_at"],
            "cleanup_status": "scheduled",
        },
    )


def rate_limit_response(rejection: RateLimitRejection) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={
            "detail": {
                "reason_code": "REQUEST_RATE_LIMITED",
                "message": "request rate limit exceeded",
                "dimension": rejection.dimension,
                "retry_after_seconds": rejection.retry_after_seconds,
            }
        },
        headers={"Retry-After": str(rejection.retry_after_seconds)},
    )


def public_dataset_release_view(release: dict[str, object]) -> dict[str, object]:
    correction_change_set = release.get("correction_change_set")
    corrections = (
        len(correction_change_set)
        if isinstance(correction_change_set, list)
        else 0
    )
    return {
        key: release[key]
        for key in (
            "id",
            "predecessor_id",
            "created_at",
            "appended_session_range",
            "session_count",
            "instrument_count",
            "canonical_schema_version",
            "canonical_tables",
            "schemas",
        )
        if key in release
    } | {"correction_count": corrections}


def page(items: list[dict[str, object]], offset: int, limit: int) -> dict[str, object]:
    selected = items[offset : offset + limit]
    return {
        "items": selected,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(selected) < len(items),
    }


def public_research_run_view(run: dict[str, object]) -> dict[str, object]:
    view = copy.deepcopy(run)
    view.pop("result_manifest_sha256", None)
    return view


def public_result_view(
    result: dict[str, object],
    *,
    daily_offset: int,
    daily_limit: int,
    position_offset: int,
    position_limit: int,
) -> dict[str, object]:
    view = copy.deepcopy(result)
    manifest = view.get("manifest")
    if isinstance(manifest, dict):
        manifest.pop("objects", None)
        manifest.pop("manifest_sha256", None)
        release = manifest.get("dataset_release")
        if isinstance(release, dict):
            release.pop("manifest_sha256", None)

    factor = view.get("factor_evaluation")
    if isinstance(factor, dict):
        horizons = factor.get("horizons")
        if isinstance(horizons, dict):
            for horizon in horizons.values():
                if isinstance(horizon, dict):
                    for key in ("alpha_checksum", "label_checksum", "source_checksum"):
                        horizon.pop(key, None)

    strategy = view.get("strategy_backtest")
    if isinstance(strategy, dict):
        strategy.pop("alpha_checksum", None)
        strategy.pop("rebalance_aggregates", None)
        strategy.pop("execution_aggregates", None)
        daily = strategy.get("daily")
        if isinstance(daily, list):
            strategy["daily"] = daily[daily_offset : daily_offset + daily_limit]
            strategy["daily_page"] = {
                "offset": daily_offset,
                "limit": daily_limit,
                "has_more": daily_offset + len(strategy["daily"]) < len(daily),
            }

    terminal = view.get("terminal_strategy_state")
    if isinstance(terminal, dict):
        positions = terminal.get("positions")
        if isinstance(positions, list):
            terminal["positions"] = positions[
                position_offset : position_offset + position_limit
            ]
            terminal["positions_page"] = {
                "offset": position_offset,
                "limit": position_limit,
                "has_more": position_offset + len(terminal["positions"]) < len(positions),
            }
    return view


def create_app(
    settings: Settings,
    *,
    tushare_transport: TushareTransport | None = None,
    runtime_ports: RuntimePorts | None = None,
    identity_verifier: IdentityVerifier | None = None,
    registration_service: RegistrationService | None = None,
) -> FastAPI:
    runtime = runtime_ports or build_runtime(settings)
    store = runtime.control_metadata
    objects = runtime.objects
    publisher = DatasetPublisher(store, objects)
    definitions = ResearchDefinitionService(store, publisher)
    research_runs = ResearchRunService(store, publisher, objects)
    tracking = DailyTrackingService(
        store,
        publisher,
        objects,
        runtime.working_cache,
    )
    tracking_operations = TrackingOperationService(store, tracking)
    tracking.reconcile_activation_staging()
    tracking.reconcile_cache_deletions()
    resource_deletion = ResourceDeletionService(
        store,
        objects,
        runtime.working_cache,
    )
    resource_deletion.reconcile_pending()
    source_authorization = SourceAuthorizationService(
        build_management_store(settings, store)
    )
    source_transport = tushare_transport or HttpTushareTransport()
    app = FastAPI(title="ThesisTrace", version="0.1.0")
    instrument_http(app)
    verifier = identity_verifier
    if settings.auth_mode == "insforge" and verifier is None:
        verifier = build_identity_verifier(
            database_url=settings.database_url,
            jwks_url=settings.insforge_jwks_url,
            issuer=settings.insforge_jwt_issuer,
            audience=settings.insforge_jwt_audience,
        )
    registration = registration_service
    if settings.auth_mode == "insforge" and registration is None:
        registration = build_registration_service(
            settings=settings,
            source_authorization=source_authorization,
        )
    rate_limiter = ApiRateLimiter(
        window_seconds=settings.api_rate_limit_window_seconds,
        user_request_limit=settings.api_user_request_limit,
        workspace_request_limit=settings.api_workspace_request_limit,
        mutation_request_limit=settings.api_mutation_request_limit,
    )

    @app.middleware("http")
    async def authenticate_product_request(request: Request, call_next):
        if settings.runtime_mode == "hosted":
            hidden_hosted_paths = {
                "/api/v1/dataset-releases/bootstrap",
                "/api/v1/dataset-releases/bootstrap-live",
                "/api/v1/dataset-releases/publish-fixture",
                "/api/v1/dataset-releases/publish-live",
                "/api/v1/sources/tushare/preflight",
            }
            if (
                request.url.path.startswith("/api/v1/objects/")
                or request.url.path in hidden_hosted_paths
            ):
                return JSONResponse(
                    status_code=404,
                    content={
                        "detail": error_detail(
                            "ROUTE_NOT_FOUND",
                            "route not found",
                        )
                    },
                )
            supplied_workspace_keys = {
                "workspace_id",
                "personal_workspace_id",
            }
            if (
                supplied_workspace_keys.intersection(request.query_params)
                or request.headers.get("X-Workspace-ID") is not None
                or request.headers.get("X-Personal-Workspace-ID") is not None
            ):
                return JSONResponse(
                    status_code=422,
                    content={
                        "detail": error_detail(
                            "CLIENT_WORKSPACE_FORBIDDEN",
                            "Personal Workspace is derived from the authenticated User",
                        )
                    },
                )
        if (
            settings.auth_mode != "insforge"
            or request.url.path
            in {"/api/v1/health", "/api/v1/live", "/api/v1/ready"}
            or not request.url.path.startswith("/api/v1/")
        ):
            return await call_next(request)
        assert verifier is not None
        try:
            request.state.identity = await run_in_threadpool(
                verifier.verify,
                request.headers.get("Authorization"),
            )
        except AuthenticationFailure as error:
            message = (
                "verified email required"
                if error.reason_code == "AUTH_EMAIL_UNVERIFIED"
                else "authentication required"
            )
            return JSONResponse(
                status_code=error.status_code,
                content={
                    "detail": error_detail(error.reason_code, message),
                },
                headers={"WWW-Authenticate": "Bearer"}
                if error.status_code == 401
                else None,
            )
        assert registration is not None
        request.state.product_identity = await run_in_threadpool(
            registration.resolve_identity,
            request.state.identity.subject,
        )
        product_identity = request.state.product_identity
        rejection = rate_limiter.check(
            subject=request.state.identity.subject,
            workspace_id=(
                None
                if product_identity is None
                else product_identity.workspace_id
            ),
            state_changing=request.method not in {"GET", "HEAD", "OPTIONS"},
        )
        if rejection is not None:
            return rate_limit_response(rejection)
        if (
            request.url.path not in {"/api/v1/session", "/api/v1/provision"}
            and product_identity is None
        ):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": error_detail(
                        "PRODUCT_PROVISIONING_REQUIRED",
                        "product provisioning is required",
                    )
                },
            )
        with authenticated_subject(request.state.identity.subject):
            return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(
        _request: Request,
        _error: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": error_detail(
                    "REQUEST_VALIDATION_FAILED",
                    "request validation failed",
                )
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(
        _request: Request,
        error: StarletteHTTPException,
    ) -> JSONResponse:
        if isinstance(error.detail, dict):
            detail = error.detail
        else:
            reason_code = (
                "ROUTE_NOT_FOUND"
                if error.status_code == 404
                else "METHOD_NOT_ALLOWED"
                if error.status_code == 405
                else f"HTTP_{error.status_code}"
            )
            detail = error_detail(reason_code, str(error.detail))
        return JSONResponse(
            status_code=error.status_code,
            content={"detail": detail},
            headers=error.headers,
        )

    @app.get("/api/v1/workspace")
    def get_workspace() -> dict[str, object]:
        return {
            "installation_id": store.installation_id(),
            "resource_counts": store.resource_counts(),
            "latest_dataset_release": store.latest_dataset_release(),
        }

    @app.get("/api/v1/session")
    def get_product_session(request: Request) -> dict[str, object]:
        if settings.auth_mode != "insforge":
            raise HTTPException(
                status_code=404,
                detail=error_detail(
                    "AUTH_NOT_CONFIGURED",
                    "hosted authentication is not configured",
                ),
            )
        identity = request.state.identity
        product_identity = request.state.product_identity
        if product_identity is not None:
            return {
                "product_state": "provisioned",
                "identity": {
                    "subject": identity.subject,
                    "email": identity.email,
                },
                "user_id": product_identity.user_id,
                "workspace_id": product_identity.workspace_id,
            }
        return {
            "product_state": "non_provisioned",
            "identity": {
                "subject": identity.subject,
                "email": identity.email,
            },
        }

    @app.post("/api/v1/provision")
    def provision_product_identity(request: Request) -> JSONResponse:
        if settings.auth_mode != "insforge" or registration is None:
            raise HTTPException(
                status_code=404,
                detail=error_detail(
                    "AUTH_NOT_CONFIGURED",
                    "hosted authentication is not configured",
                ),
            )
        try:
            result = registration.provision(request.state.identity)
        except ProvisioningError as error:
            raise HTTPException(
                status_code=403
                if error.reason_code == "INVITATION_NOT_ELIGIBLE"
                else 409,
                detail=error_detail(
                    error.reason_code,
                    "product provisioning is not available",
                ),
            ) from error
        return JSONResponse(
            status_code=201 if result.created else 200,
            content={
                "product_state": "provisioned",
                "invitation_id": result.invitation_id,
                "user_id": result.identity.user_id,
                "workspace_id": result.identity.workspace_id,
                "created": result.created,
            },
        )

    @app.get("/api/v1/research-definitions")
    def list_research_definitions(
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=100),
    ) -> dict[str, object]:
        return page(store.list_research_drafts(), offset, limit)

    @app.post("/api/v1/research-definitions")
    def create_research_definition(content: dict[str, object]) -> JSONResponse:
        reject_client_workspace_identity(content)
        return JSONResponse(status_code=201, content=definitions.create_draft(content))

    @app.get("/api/v1/research-definitions/{draft_id}")
    def get_research_definition(draft_id: str) -> dict[str, object]:
        draft = store.research_draft(draft_id)
        if draft is None:
            raise HTTPException(
                status_code=404,
                detail=error_detail(
                    "RESEARCH_DEFINITION_NOT_FOUND",
                    "research definition draft not found",
                ),
            )
        return draft

    @app.put("/api/v1/research-definitions/{draft_id}")
    def update_research_definition(draft_id: str, content: dict[str, object]) -> dict[str, object]:
        reject_client_workspace_identity(content)
        draft = definitions.update_draft(draft_id, content)
        if draft is None:
            raise HTTPException(
                status_code=404,
                detail=error_detail(
                    "RESEARCH_DEFINITION_NOT_FOUND",
                    "research definition draft not found",
                ),
            )
        return draft

    @app.post("/api/v1/research-definitions/{draft_id}/runs")
    def request_research_run(
        draft_id: str,
        idempotency_key: str = Header(min_length=1, alias="Idempotency-Key"),
    ) -> JSONResponse:
        try:
            frozen, run, created = definitions.request_run(draft_id, idempotency_key)
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=error_detail(
                    "RESEARCH_DEFINITION_NOT_FOUND",
                    "research definition draft not found",
                ),
            ) from error
        except DefinitionValidationError as error:
            raise HTTPException(status_code=422, detail={"errors": error.errors}) from error
        except QuotaExceededError as error:
            raise HTTPException(
                status_code=409,
                detail=quota_error_detail(error),
            ) from error
        if created:
            runtime.execution_dispatch.dispatch("research_run", str(run["id"]))
        return JSONResponse(
            status_code=202 if created else 200,
            content={
                "frozen_definition": frozen,
                "run": (
                    public_research_run_view(run)
                    if settings.runtime_mode == "hosted"
                    else run
                ),
            },
        )

    @app.get("/api/v1/research-definition-versions/{version_id}")
    def get_research_definition_version(version_id: str) -> dict[str, object]:
        frozen = store.frozen_research_definition(version_id)
        if frozen is None:
            raise HTTPException(
                status_code=404,
                detail=error_detail(
                    "RESEARCH_DEFINITION_VERSION_NOT_FOUND",
                    "frozen definition not found",
                ),
            )
        return frozen

    @app.get("/api/v1/research-definition-versions")
    def list_research_definition_versions(
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=100),
    ) -> dict[str, object]:
        return page(store.list_frozen_research_definitions(), offset, limit)

    @app.get("/api/v1/research-runs")
    def list_research_runs(
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=100),
    ) -> dict[str, object]:
        runs = store.list_research_runs()
        if settings.runtime_mode == "hosted":
            runs = [public_research_run_view(run) for run in runs]
        return page(runs, offset, limit)

    @app.get("/api/v1/research-runs/{run_id}")
    def get_research_run(run_id: str) -> dict[str, object]:
        run = store.research_run(run_id)
        if run is None:
            raise HTTPException(
                status_code=404,
                detail=error_detail("RESEARCH_RUN_NOT_FOUND", "ResearchRun not found"),
            )
        return (
            public_research_run_view(run)
            if settings.runtime_mode == "hosted"
            else run
        )

    @app.get("/api/v1/research-runs/{run_id}/attempts/{ordinal}")
    def get_research_run_attempt(run_id: str, ordinal: int) -> dict[str, object]:
        run = store.research_run(run_id)
        if run is None:
            raise HTTPException(
                status_code=404,
                detail=error_detail("RESEARCH_RUN_NOT_FOUND", "ResearchRun not found"),
            )
        attempts = run.get("attempts")
        if isinstance(attempts, list):
            for attempt in attempts:
                if isinstance(attempt, dict) and attempt.get("ordinal") == ordinal:
                    return attempt
        raise HTTPException(
            status_code=404,
            detail=error_detail(
                "RESEARCH_RUN_ATTEMPT_NOT_FOUND",
                "ResearchRun Attempt not found",
            ),
        )

    @app.get("/api/v1/research-runs/{run_id}/result")
    def get_research_run_result(
        run_id: str,
        daily_offset: int = Query(0, ge=0),
        daily_limit: int = Query(756, ge=1, le=756),
        position_offset: int = Query(0, ge=0),
        position_limit: int = Query(100, ge=1, le=100),
    ) -> dict[str, object]:
        try:
            result = research_runs.result_view(run_id)
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=error_detail("RESEARCH_RUN_NOT_FOUND", "ResearchRun not found"),
            ) from error
        if result is None:
            raise HTTPException(
                status_code=409,
                detail=error_detail(
                    "RESULT_BUNDLE_UNAVAILABLE",
                    "ResearchRun has no successful Result Bundle",
                ),
            )
        return (
            public_result_view(
                result,
                daily_offset=daily_offset,
                daily_limit=daily_limit,
                position_offset=position_offset,
                position_limit=position_limit,
            )
            if settings.runtime_mode == "hosted"
            else result
        )

    @app.post("/api/v1/research-runs/{run_id}/cancel")
    def cancel_research_run(run_id: str) -> dict[str, object]:
        run = store.cancel_research_run(run_id)
        if run is None:
            raise HTTPException(
                status_code=404,
                detail=error_detail("RESEARCH_RUN_NOT_FOUND", "ResearchRun not found"),
            )
        if run["status"] == "cancelled":
            run = recover_staged_research_run(store, objects, run_id)
        return (
            public_research_run_view(run)
            if settings.runtime_mode == "hosted"
            else run
        )

    @app.delete("/api/v1/research-runs/{run_id}")
    def delete_research_run(run_id: str) -> JSONResponse:
        try:
            tombstone = resource_deletion.delete_research_run(
                run_id,
                actor=verified_subject() or "local-user",
            )
        except ResourceDeletionError as error:
            raise HTTPException(
                status_code=(
                    404 if error.reason_code == "RESOURCE_NOT_FOUND" else 409
                ),
                detail=error_detail(error.reason_code, str(error)),
            ) from error
        return deletion_response(tombstone)

    @app.post("/api/v1/research-runs/{run_id}/rerun")
    def rerun_research(
        run_id: str,
        idempotency_key: str = Header(min_length=1, alias="Idempotency-Key"),
    ) -> JSONResponse:
        try:
            run, created = store.create_research_rerun(run_id, idempotency_key)
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=error_detail("RESEARCH_RUN_NOT_FOUND", "ResearchRun not found"),
            ) from error
        except QuotaExceededError as error:
            raise HTTPException(
                status_code=409,
                detail=quota_error_detail(error),
            ) from error
        if created:
            runtime.execution_dispatch.dispatch("research_run", str(run["id"]))
        return JSONResponse(
            status_code=202 if created else 200,
            content=(
                public_research_run_view(run)
                if settings.runtime_mode == "hosted"
                else run
            ),
        )

    @app.post("/api/v1/research-runs/{run_id}/daily-tracks")
    def activate_daily_track(
        run_id: str,
        idempotency_key: str = Header(min_length=1, alias="Idempotency-Key"),
    ) -> JSONResponse:
        try:
            track, created = tracking.activate(run_id, idempotency_key)
        except QuotaExceededError as error:
            raise HTTPException(
                status_code=409,
                detail=quota_error_detail(error),
            ) from error
        except StorageAdmissionError as error:
            raise HTTPException(
                status_code=507,
                detail={
                    "reason_code": error.reason_code,
                    "message": str(error),
                    "dimension": error.dimension,
                    "limit": error.limit,
                },
            ) from error
        except DailyTrackingError as error:
            raise HTTPException(
                status_code=409,
                detail=error_detail("DAILY_TRACK_CONFLICT", str(error)),
            ) from error
        if created:
            runtime.execution_dispatch.dispatch("daily_track", str(track["id"]))
        view = tracking.bounded_track_view(str(track["id"]))
        if view is None:
            raise RuntimeError("activated DailyTrack disappeared")
        return JSONResponse(
            status_code=201 if created else 200,
            content=view,
        )

    @app.get("/api/v1/daily-tracks")
    def list_daily_tracks(
        offset: int = Query(0, ge=0),
        limit: int = Query(10, ge=1, le=10),
    ) -> dict[str, object]:
        return tracking.list_track_views(offset=offset, limit=limit)

    @app.get("/api/v1/daily-tracks/{track_id}")
    def get_daily_track(track_id: str) -> dict[str, object]:
        track = tracking.bounded_track_view(track_id)
        if track is None:
            raise HTTPException(
                status_code=404,
                detail=error_detail("DAILY_TRACK_NOT_FOUND", "DailyTrack not found"),
            )
        return track

    def require_track_child(
        child: dict[str, object] | None,
        reason_code: str,
        label: str,
    ) -> dict[str, object]:
        if child is not None:
            return child
        raise HTTPException(
            status_code=404,
            detail=error_detail(reason_code, f"{label} not found"),
        )

    @app.get("/api/v1/daily-tracks/{track_id}/generations/{generation_id}")
    def get_daily_track_generation(track_id: str, generation_id: str) -> dict[str, object]:
        return require_track_child(
            tracking.tracking_generation(track_id, generation_id),
            "TRACKING_GENERATION_NOT_FOUND",
            "Tracking Generation",
        )

    @app.get("/api/v1/daily-tracks/{track_id}/advances/{advance_id}")
    def get_daily_track_advance(track_id: str, advance_id: str) -> dict[str, object]:
        return require_track_child(
            tracking.tracking_advance(track_id, advance_id),
            "TRACKING_ADVANCE_NOT_FOUND",
            "Tracking Advance",
        )

    @app.get("/api/v1/daily-tracks/{track_id}/checkpoints/{checkpoint_id}")
    def get_daily_track_checkpoint(
        track_id: str,
        checkpoint_id: str,
        limit: int = Query(252, ge=1, le=252),
    ) -> dict[str, object]:
        try:
            return tracking.checkpoint_product_view(
                track_id,
                checkpoint_id,
                limit=limit,
            )
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=error_detail(
                    "TRACKING_CHECKPOINT_NOT_FOUND",
                    "Tracking Checkpoint not found",
                ),
            ) from error
        except DailyTrackingError as error:
            raise HTTPException(
                status_code=409,
                detail=error_detail("DAILY_TRACK_CONFLICT", str(error)),
            ) from error

    @app.get("/api/v1/daily-tracks/{track_id}/current")
    def get_daily_track_current_view(
        track_id: str,
        limit: int = Query(252, ge=1, le=252),
    ) -> dict[str, object]:
        try:
            return tracking.current_view(track_id, limit=limit)
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=error_detail("DAILY_TRACK_NOT_FOUND", "DailyTrack not found"),
            ) from error
        except DailyTrackingError as error:
            raise HTTPException(
                status_code=409,
                detail=error_detail("DAILY_TRACK_CONFLICT", str(error)),
            ) from error

    @app.post("/api/v1/daily-tracks/{track_id}/stop")
    def stop_daily_track(track_id: str) -> dict[str, object]:
        track = tracking.stop(track_id)
        if track is None:
            raise HTTPException(
                status_code=404,
                detail=error_detail("DAILY_TRACK_NOT_FOUND", "DailyTrack not found"),
            )
        view = tracking.bounded_track_view(track_id)
        if view is None:
            raise RuntimeError("stopped DailyTrack disappeared")
        return view

    @app.delete("/api/v1/daily-tracks/{track_id}")
    def delete_daily_track(track_id: str) -> JSONResponse:
        try:
            tombstone = resource_deletion.delete_daily_track(
                track_id,
                actor=verified_subject() or "local-user",
            )
        except ResourceDeletionError as error:
            raise HTTPException(
                status_code=(
                    404 if error.reason_code == "RESOURCE_NOT_FOUND" else 409
                ),
                detail=error_detail(error.reason_code, str(error)),
            ) from error
        return deletion_response(tombstone)

    @app.post("/api/v1/daily-tracks/{track_id}/kernel-upgrade")
    def upgrade_daily_track_kernel(
        track_id: str,
        request: KernelUpgradeRequest,
    ) -> dict[str, object]:
        if settings.runtime_mode == "hosted":
            raise HTTPException(
                status_code=404,
                detail=error_detail(
                    "DAILY_TRACK_NOT_FOUND",
                    "DailyTrack not found",
                ),
            )
        try:
            track = tracking.upgrade_kernel(
                track_id,
                calculation_kernel=request.calculation_kernel,
                numeric_execution_contract=request.numeric_execution_contract,
            )
            view = tracking.bounded_track_view(str(track["id"]))
            if view is None:
                raise KeyError(track_id)
            return view
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=error_detail("DAILY_TRACK_NOT_FOUND", "DailyTrack not found"),
            ) from error
        except DailyTrackingError as error:
            raise HTTPException(
                status_code=409,
                detail=error_detail("DAILY_TRACK_CONFLICT", str(error)),
            ) from error

    @app.post("/api/v1/daily-tracks/{track_id}/verify-equivalence")
    def verify_daily_track(track_id: str) -> dict[str, object]:
        if settings.runtime_mode == "hosted":
            raise HTTPException(
                status_code=404,
                detail=error_detail(
                    "DAILY_TRACK_NOT_FOUND",
                    "DailyTrack not found",
                ),
            )
        try:
            return tracking.verify_equivalence(track_id)
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=error_detail("DAILY_TRACK_NOT_FOUND", "DailyTrack not found"),
            ) from error
        except EquivalenceError as error:
            raise HTTPException(
                status_code=409,
                detail=error_detail("EQUIVALENCE_MISMATCH", str(error)),
            ) from error
        except DailyTrackingError as error:
            raise HTTPException(
                status_code=409,
                detail=error_detail("DAILY_TRACK_CONFLICT", str(error)),
            ) from error

    @app.post(
        "/api/v1/daily-tracks/{track_id}/equivalence-requests",
    )
    def request_daily_track_equivalence(
        track_id: str,
        idempotency_key: str = Header(
            min_length=1,
            alias="Idempotency-Key",
        ),
    ) -> JSONResponse:
        try:
            request, created = tracking_operations.request_equivalence(
                track_id,
                idempotency_key,
            )
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=error_detail(
                    "DAILY_TRACK_NOT_FOUND",
                    "DailyTrack not found",
                ),
            ) from error
        except QuotaExceededError as error:
            raise HTTPException(
                status_code=409,
                detail=quota_error_detail(error),
            ) from error
        return JSONResponse(
            status_code=202 if created else 200,
            content=request,
        )

    @app.get(
        "/api/v1/daily-tracks/{track_id}/equivalence-requests/{request_id}"
    )
    def get_daily_track_equivalence(
        track_id: str,
        request_id: str,
    ) -> dict[str, object]:
        request = tracking_operations.equivalence_request(request_id)
        if (
            request is None
            or request["daily_track_id"] != track_id
        ):
            raise HTTPException(
                status_code=404,
                detail=error_detail(
                    "EQUIVALENCE_REQUEST_NOT_FOUND",
                    "Equivalence request not found",
                ),
            )
        return request

    @app.post(
        "/api/v1/daily-tracks/{track_id}/equivalence-requests/"
        "{request_id}/cancel"
    )
    def cancel_daily_track_equivalence(
        track_id: str,
        request_id: str,
    ) -> dict[str, object]:
        request = tracking_operations.equivalence_request(request_id)
        if (
            request is None
            or request["daily_track_id"] != track_id
        ):
            raise HTTPException(
                status_code=404,
                detail=error_detail(
                    "EQUIVALENCE_REQUEST_NOT_FOUND",
                    "Equivalence request not found",
                ),
            )
        return tracking_operations.cancel_equivalence(
            request_id,
            enqueue_workflow_cancellation=(
                settings.runtime_mode == "hosted"
            ),
        )

    @app.get("/api/v1/health")
    def get_health() -> dict[str, object]:
        heartbeat = store.last_worker_heartbeat()
        worker_available = (
            heartbeat is not None
            and (datetime.now(UTC) - heartbeat).total_seconds()
            <= settings.worker_stale_after_seconds
        )
        object_store_available = objects.ready()
        status = "available" if worker_available and object_store_available else "degraded"
        return {
            "status": status,
            "components": {
                "database": {"status": "available"},
                "object_store": {
                    "status": "available" if object_store_available else "unavailable"
                },
                "worker": {
                    "status": "available" if worker_available else "unavailable",
                    "last_heartbeat_at": heartbeat.isoformat() if heartbeat else None,
                },
            },
        }

    @app.get("/api/v1/live")
    def get_liveness() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/api/v1/ready")
    def get_readiness():
        try:
            store.last_worker_heartbeat()
            object_store_ready = objects.ready()
        except Exception:
            object_store_ready = False
        if not object_store_ready:
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready"},
            )
        return {"status": "ready"}

    @app.post("/api/v1/dataset-releases/bootstrap")
    def bootstrap_dataset_release(
        request: BootstrapRequest,
        idempotency_key: str = Header(min_length=1, alias="Idempotency-Key"),
    ) -> JSONResponse:
        try:
            release, created = publisher.bootstrap(idempotency_key, request.fixture)
        except DatasetPublicationConflict as error:
            raise HTTPException(
                status_code=409,
                detail={
                    "reason_code": "LATEST_RELEASE_CHANGED",
                    "message": str(error),
                },
            ) from error
        except InvalidFixtureError as error:
            raise HTTPException(
                status_code=422,
                detail=error_detail("DATASET_VALIDATION_FAILED", str(error)),
            ) from error
        return JSONResponse(
            status_code=201 if created else 200,
            content={"status": "succeeded", "release": release},
        )

    @app.post("/api/v1/sources/tushare/preflight")
    def preflight_tushare() -> dict[str, object]:
        if not settings.tushare_token:
            raise HTTPException(
                status_code=409,
                detail={"reason_code": "TOKEN_MISSING", "source_code": None},
            )
        adapter = TushareAdapter(
            token=settings.tushare_token,
            transport=source_transport,
        )
        try:
            return adapter.preflight()
        except TushareSourceError as error:
            raise HTTPException(status_code=424, detail=error.diagnostic()) from error

    @app.post("/api/v1/dataset-releases/bootstrap-live")
    def bootstrap_live_dataset_release(
        request: LiveBootstrapRequest,
        idempotency_key: str = Header(min_length=1, alias="Idempotency-Key"),
    ) -> JSONResponse:
        if not source_authorization.is_authorized():
            raise HTTPException(
                status_code=409,
                detail=error_detail(
                    "SOURCE_AUTHORIZATION_REQUIRED",
                    "hosted shared Tushare use requires an accepted Operator declaration",
                ),
            )
        if not settings.tushare_token:
            raise HTTPException(
                status_code=409,
                detail={"reason_code": "TOKEN_MISSING", "source_code": None},
            )
        adapter = TushareAdapter(
            token=settings.tushare_token,
            transport=source_transport,
        )
        try:
            adapter.preflight()
            snapshot = adapter.collect_bootstrap_snapshot(request.as_of)
            source, canonical = normalize_tushare_snapshot(snapshot)
            release, created = publisher.bootstrap_documents(
                idempotency_key,
                source=source,
                canonical=canonical,
                source_kind="source_tushare",
                source_schema="tushare-v1",
            )
        except TushareSourceError as error:
            raise HTTPException(status_code=424, detail=error.diagnostic()) from error
        except DatasetPublicationConflict as error:
            raise HTTPException(
                status_code=409,
                detail={
                    "reason_code": "LATEST_RELEASE_CHANGED",
                    "message": str(error),
                },
            ) from error
        except InvalidFixtureError as error:
            raise HTTPException(
                status_code=422,
                detail=error_detail("DATASET_VALIDATION_FAILED", str(error)),
            ) from error
        return JSONResponse(
            status_code=201 if created else 200,
            content={"status": "succeeded", "release": release},
        )

    @app.post("/api/v1/dataset-releases/publish-fixture")
    def publish_fixture_increment(
        request: FixtureIncrementRequest,
        idempotency_key: str = Header(min_length=1, alias="Idempotency-Key"),
    ) -> JSONResponse:
        try:
            release, created = publisher.publish_fixture_increment(
                idempotency_key,
                new_sessions=request.new_sessions,
                corrections=[item.model_dump() for item in request.corrections],
            )
        except DatasetPublicationConflict as error:
            raise HTTPException(
                status_code=409,
                detail={
                    "reason_code": "LATEST_RELEASE_CHANGED",
                    "message": str(error),
                },
            ) from error
        except (InvalidFixtureError, ValueError) as error:
            raise HTTPException(
                status_code=422,
                detail=error_detail("DATASET_VALIDATION_FAILED", str(error)),
            ) from error
        try:
            enqueue_failures = tracking.enqueue_active_tracks(str(release["id"]))
        except Exception:
            enqueue_failures = [
                {
                    "track_id": "*",
                    "reason_code": "TRACK_ENQUEUE_FAILED",
                    "message": "tracking reconciliation will retry",
                }
            ]
        return JSONResponse(
            status_code=201 if created else 200,
            content={
                "status": "succeeded",
                "release": release,
                "tracking_enqueue_failures": enqueue_failures,
            },
        )

    @app.post("/api/v1/dataset-releases/publish-live")
    def publish_live_increment(
        request: LiveBootstrapRequest,
        idempotency_key: str = Header(min_length=1, alias="Idempotency-Key"),
    ) -> JSONResponse:
        if not source_authorization.is_authorized():
            raise HTTPException(
                status_code=409,
                detail=error_detail(
                    "SOURCE_AUTHORIZATION_REQUIRED",
                    "hosted shared Tushare use requires an accepted Operator declaration",
                ),
            )
        existing = store.dataset_release_for_idempotency_key(idempotency_key)
        if existing is not None:
            try:
                enqueue_failures = tracking.enqueue_active_tracks(str(existing["id"]))
            except Exception:
                enqueue_failures = [
                    {
                        "track_id": "*",
                        "reason_code": "TRACK_ENQUEUE_FAILED",
                        "message": "tracking reconciliation will retry",
                    }
                ]
            return JSONResponse(
                status_code=200,
                content={
                    "status": "succeeded",
                    "release": existing,
                    "tracking_enqueue_failures": enqueue_failures,
                },
            )
        if not settings.tushare_token:
            raise HTTPException(
                status_code=409,
                detail={"reason_code": "TOKEN_MISSING", "source_code": None},
            )
        predecessor = store.latest_dataset_release()
        if predecessor is None:
            raise HTTPException(
                status_code=409,
                detail={"reason_code": "LIVE_BOOTSTRAP_REQUIRED"},
            )
        schemas = predecessor.get("schemas")
        if not isinstance(schemas, list) or not any(
            isinstance(item, dict) and item.get("family") == "source_tushare"
            for item in schemas
        ):
            raise HTTPException(
                status_code=409,
                detail={"reason_code": "LIVE_PREDECESSOR_REQUIRED"},
            )
        try:
            canonical = publisher.materialize_canonical(predecessor)
            instruments = canonical.get("instruments")
            calendar = canonical.get("research_calendar")
            if (
                not isinstance(instruments, list)
                or not isinstance(calendar, list)
                or not calendar
            ):
                raise InvalidFixtureError("predecessor canonical data is incomplete")
            adapter = TushareAdapter(
                token=settings.tushare_token,
                transport=source_transport,
            )
            snapshot = adapter.collect_incremental_snapshot(
                last_session=str(calendar[-1]),
                known_ts_codes={
                    str(item["ts_code"])
                    for item in instruments
                    if isinstance(item, dict)
                },
                as_of=request.as_of,
            )
            source, canonical_delta = normalize_tushare_increment(snapshot, canonical)
            release, created = publisher.publish_increment_documents(
                idempotency_key,
                source=source,
                canonical_delta=canonical_delta,
                source_schema="tushare-v1",
            )
        except TushareSourceError as error:
            raise HTTPException(status_code=424, detail=error.diagnostic()) from error
        except DatasetPublicationConflict as error:
            raise HTTPException(
                status_code=409,
                detail={
                    "reason_code": "LATEST_RELEASE_CHANGED",
                    "message": str(error),
                },
            ) from error
        except InvalidFixtureError as error:
            raise HTTPException(
                status_code=422,
                detail=error_detail("DATASET_VALIDATION_FAILED", str(error)),
            ) from error
        try:
            enqueue_failures = tracking.enqueue_active_tracks(str(release["id"]))
        except Exception:
            enqueue_failures = [
                {
                    "track_id": "*",
                    "reason_code": "TRACK_ENQUEUE_FAILED",
                    "message": "tracking reconciliation will retry",
                }
            ]
        return JSONResponse(
            status_code=201 if created else 200,
            content={
                "status": "succeeded",
                "release": release,
                "tracking_enqueue_failures": enqueue_failures,
            },
        )

    @app.get("/api/v1/dataset-releases")
    def list_dataset_releases(
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=100),
    ) -> dict[str, object]:
        releases = store.list_dataset_releases()
        if settings.runtime_mode == "hosted":
            releases = [public_dataset_release_view(release) for release in releases]
        return page(releases, offset, limit)

    @app.get("/api/v1/dataset-releases/{release_id}")
    def get_dataset_release(release_id: str) -> dict[str, object]:
        release = store.dataset_release(release_id)
        if release is None:
            raise HTTPException(
                status_code=404,
                detail=error_detail("DATASET_RELEASE_NOT_FOUND", "dataset release not found"),
            )
        if settings.runtime_mode == "hosted":
            return public_dataset_release_view(release)
        return release

    @app.get("/api/v1/dataset-releases/{release_id}/data-contract")
    def get_dataset_contract(release_id: str) -> dict[str, object]:
        release = store.dataset_release(release_id)
        if release is None:
            raise HTTPException(
                status_code=404,
                detail=error_detail("DATASET_RELEASE_NOT_FOUND", "dataset release not found"),
            )
        try:
            return publisher.data_contract(release)
        except InvalidFixtureError as error:
            raise HTTPException(
                status_code=409,
                detail=error_detail("DATA_CONTRACT_UNAVAILABLE", str(error)),
            ) from error

    @app.get("/api/v1/objects/{digest}")
    def get_object(digest: str) -> FileResponse:
        if (
            settings.runtime_mode == "hosted"
            or not isinstance(objects, ImmutableObjectStore)
        ):
            raise HTTPException(
                status_code=404,
                detail=error_detail(
                    "IMMUTABLE_OBJECT_NOT_FOUND",
                    "object not found",
                ),
            )
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise HTTPException(
                status_code=404,
                detail=error_detail("IMMUTABLE_OBJECT_NOT_FOUND", "object not found"),
            )
        json_path = objects.path_for(digest)
        parquet_path = objects.parquet_path_for(digest)
        if json_path.is_file():
            path = json_path
            media_type = "application/json"
        elif parquet_path.is_file():
            path = parquet_path
            media_type = "application/vnd.apache.parquet"
        else:
            raise HTTPException(
                status_code=404,
                detail=error_detail(
                    "IMMUTABLE_OBJECT_NOT_FOUND",
                    "object not found",
                ),
            )
        return FileResponse(
            path,
            media_type=media_type,
            headers={"ETag": f'"sha256:{digest}"', "Cache-Control": "public, immutable"},
        )

    return app


def reject_client_workspace_identity(content: dict[str, object]) -> None:
    forbidden = {"workspace_id", "personal_workspace_id"}
    if forbidden.intersection(content):
        raise HTTPException(
            status_code=422,
            detail=error_detail(
                "CLIENT_WORKSPACE_FORBIDDEN",
                "Personal Workspace is derived from the authenticated User",
            ),
        )


def main() -> None:
    configure_observability("api")
    uvicorn.run(
        create_app(settings_from_environment()),
        host=os.environ.get("THESISTRACE_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("THESISTRACE_API_PORT", "8000")),
        log_config=None,
    )
