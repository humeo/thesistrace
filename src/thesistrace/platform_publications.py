import json
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Protocol
from uuid import uuid4

from thesistrace.activity_contract import (
    CooperativeActivityCancellation,
    is_resource_exhaustion,
    should_retry_resource_exhaustion,
)
from thesistrace.config import Settings
from thesistrace.datasets import DatasetPublisher, InvalidFixtureError
from thesistrace.ports import ObjectStorePort, ObjectStoreStagePort
from thesistrace.storage_admission import (
    StorageAdmissionError,
    publication_storage_objects,
)
from thesistrace.tushare_source import (
    HttpTushareTransport,
    TushareAdapter,
    TushareTransport,
    normalize_tushare_increment,
    normalize_tushare_snapshot,
)

logger = logging.getLogger(__name__)
PUBLICATION_KINDS = {
    "fixture_bootstrap",
    "fixture_increment",
    "live_bootstrap",
    "live_increment",
}
MAX_FIXTURE_CORRECTIONS = 100
MAX_PUBLICATION_PARAMETERS_BYTES = 64 * 1024


class SourceAuthorizationGate(Protocol):
    def is_authorized(self) -> bool: ...


class DatasetPublicationRequestStore(Protocol):
    def request_dataset_publication(
        self,
        record: dict[str, object],
        audit_event: dict[str, object] | None,
    ) -> tuple[dict[str, object], bool]: ...

    def append_management_audit_event(self, event: dict[str, object]) -> None: ...


class DatasetPublicationRequestError(RuntimeError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class DatasetPublicationFenced(RuntimeError):
    pass


class DatasetPublicationRequestService:
    def __init__(
        self,
        store: DatasetPublicationRequestStore,
        source_authorization: SourceAuthorizationGate,
    ) -> None:
        self.store = store
        self.source_authorization = source_authorization

    def request(
        self,
        *,
        actor: str,
        request_version: str,
        kind: str,
        parameters: dict[str, object],
        idempotency_key: str,
    ) -> tuple[dict[str, object], bool]:
        return self._request(
            actor=actor.strip(),
            request_version=request_version,
            kind=kind,
            parameters=parameters,
            idempotency_key=idempotency_key.strip(),
            trigger_kind="operator",
            audit=True,
        )

    def request_scheduled(
        self,
        *,
        schedule_id: str,
        scheduled_for: str,
        request_version: str,
        kind: str,
        parameters: dict[str, object],
    ) -> tuple[dict[str, object], bool]:
        normalized_schedule_id = schedule_id.strip()
        normalized_scheduled_for = scheduled_for.strip()
        if not normalized_schedule_id or not normalized_scheduled_for:
            raise DatasetPublicationRequestError(
                "DATASET_SCHEDULE_INVALID",
                "schedule id and scheduled instant are required",
            )
        return self._request(
            actor=f"temporal-schedule:{normalized_schedule_id}",
            request_version=request_version,
            kind=kind,
            parameters=parameters,
            idempotency_key=(
                f"schedule:{normalized_schedule_id}:{normalized_scheduled_for}"
            ),
            trigger_kind="schedule",
            audit=False,
        )

    def _request(
        self,
        *,
        actor: str,
        request_version: str,
        kind: str,
        parameters: dict[str, object],
        idempotency_key: str,
        trigger_kind: str,
        audit: bool,
    ) -> tuple[dict[str, object], bool]:
        occurred_at = datetime.now(UTC).isoformat()
        reason_code = self._validate(
            actor=actor,
            request_version=request_version,
            kind=kind,
            parameters=parameters,
            idempotency_key=idempotency_key,
        )
        if reason_code is None and kind.startswith("live_"):
            if not self.source_authorization.is_authorized():
                reason_code = "SOURCE_AUTHORIZATION_REQUIRED"
        if reason_code is not None:
            if audit:
                self.store.append_management_audit_event(
                    publication_audit_event(
                        actor=actor or "unknown",
                        occurred_at=occurred_at,
                        outcome="rejected",
                        reason_code=reason_code,
                        subject_id="dataset-publication-request",
                        request_version=request_version,
                        kind=kind,
                        trigger_kind=trigger_kind,
                    )
                )
            raise DatasetPublicationRequestError(
                reason_code,
                publication_request_error_message(reason_code),
            )
        publication_id = f"dsp_{uuid4().hex[:20]}"
        record = {
            "id": publication_id,
            "request_version": request_version,
            "kind": kind,
            "parameters": parameters,
            "idempotency_key": idempotency_key,
            "trigger_kind": trigger_kind,
            "status": "queued",
            "created_at": occurred_at,
            "updated_at": occurred_at,
        }
        audit_event = (
            publication_audit_event(
                actor=actor,
                occurred_at=occurred_at,
                outcome="succeeded",
                reason_code=None,
                subject_id=publication_id,
                request_version=request_version,
                kind=kind,
                trigger_kind=trigger_kind,
            )
            if audit
            else None
        )
        return self.store.request_dataset_publication(record, audit_event)

    @staticmethod
    def _validate(
        *,
        actor: str,
        request_version: str,
        kind: str,
        parameters: dict[str, object],
        idempotency_key: str,
    ) -> str | None:
        if not actor:
            return "OPERATOR_ACTOR_REQUIRED"
        if not idempotency_key:
            return "IDEMPOTENCY_KEY_REQUIRED"
        if request_version != "v1":
            return "DATASET_PUBLICATION_VERSION_UNSUPPORTED"
        if kind not in PUBLICATION_KINDS:
            return "DATASET_PUBLICATION_KIND_UNSUPPORTED"
        try:
            parameter_bytes = len(
                json.dumps(
                    parameters,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
        except (TypeError, ValueError):
            return "DATASET_PUBLICATION_PARAMETERS_INVALID"
        if parameter_bytes > MAX_PUBLICATION_PARAMETERS_BYTES:
            return "DATASET_PUBLICATION_PARAMETERS_INVALID"
        if kind == "fixture_bootstrap":
            if parameters != {"fixture": "v1"}:
                return "DATASET_PUBLICATION_PARAMETERS_INVALID"
        elif kind == "fixture_increment":
            sessions = parameters.get("new_sessions")
            corrections = parameters.get("corrections")
            if (
                isinstance(sessions, bool)
                or not isinstance(sessions, int)
                or not 1 <= sessions <= 20
                or not isinstance(corrections, list)
                or len(corrections) > MAX_FIXTURE_CORRECTIONS
            ):
                return "DATASET_PUBLICATION_PARAMETERS_INVALID"
        else:
            as_of = parameters.get("as_of")
            try:
                if not isinstance(as_of, str):
                    raise ValueError
                date.fromisoformat(as_of)
            except ValueError:
                return "DATASET_PUBLICATION_PARAMETERS_INVALID"
            if set(parameters) != {"as_of"}:
                return "DATASET_PUBLICATION_PARAMETERS_INVALID"
        return None


class DatasetPublicationService:
    def __init__(
        self,
        metadata,
        objects: ObjectStorePort,
        *,
        settings: Settings | None = None,
        tushare_transport: TushareTransport | None = None,
        progress: Callable[[str], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> None:
        self.metadata = metadata
        self.objects = objects
        self.settings = settings
        self.tushare_transport = tushare_transport or HttpTushareTransport()
        self.progress = progress or (lambda _stage: None)
        self.cancellation_requested = cancellation_requested

    def execute(self, publication_id: str) -> dict[str, object]:
        current = self.recover(publication_id)
        if current["status"] in {"succeeded", "failed", "cancelled"}:
            return current
        claimed = self.metadata.claim_dataset_publication(publication_id)
        if claimed is None:
            latest = self.metadata.dataset_publication(publication_id)
            if latest is None:
                raise KeyError(publication_id)
            return latest
        publication, attempt = claimed
        attempt_id = str(attempt["id"])
        ordinal = int(attempt["ordinal"])
        try:
            self.progress("claimed")
            with self.objects.publication_guard(publication_id):
                latest = self.metadata.dataset_publication(publication_id)
                if latest is None:
                    raise KeyError(publication_id)
                if latest["status"] != "running":
                    return latest
                with self.objects.stage(
                    publication_id,
                    attempt_id,
                    cleanup_uncommitted_payloads=True,
                ) as staged:
                    release = self._build_candidate(publication, staged)
                    self.progress("validated")
                    with self.metadata.storage_mutation_fence():
                        with staged.publication(
                            manifest_sha256=str(release["manifest_sha256"])
                        ):
                            published = (
                                self.metadata.publish_dataset_publication_success(
                                    publication_id=publication_id,
                                    attempt_id=attempt_id,
                                    release=release,
                                    idempotency_key=str(
                                        publication["idempotency_key"]
                                    ),
                                    storage_objects=publication_storage_objects(
                                        release
                                    ),
                                    cancellation_requested=(
                                        self.cancellation_requested
                                    ),
                                )
                            )
                            if not published:
                                raise DatasetPublicationFenced
        except DatasetPublicationFenced:
            return self.recover(publication_id)
        except CooperativeActivityCancellation:
            self.metadata.request_dataset_publication_cancellation(
                publication_id
            )
            return self.recover(publication_id)
        except Exception as error:
            latest = self.metadata.dataset_publication(publication_id)
            if latest is not None and latest["status"] == "succeeded":
                return self.recover(publication_id)
            storage_rejected = isinstance(error, StorageAdmissionError)
            exhausted = is_resource_exhaustion(error)
            if storage_rejected:
                reason_code = error.reason_code
                message = str(error)
            elif exhausted:
                reason_code = "RESOURCE_EXHAUSTED"
                message = "accepted Data Worker resource envelope was exhausted"
            else:
                reason_code = "DATASET_PUBLICATION_FAILED"
                message = "Dataset Publication failed validation or execution"
            diagnostic = {
                "reason_code": reason_code,
                "message": message,
                "correlation_id": attempt_id,
            }
            if storage_rejected:
                diagnostic["dimension"] = error.dimension
                diagnostic["limit"] = error.limit
            logger.error(
                "Dataset Publication failed publication_id=%s "
                "attempt_id=%s error_type=%s reason_code=%s",
                publication_id,
                attempt_id,
                type(error).__name__,
                reason_code,
            )
            self.metadata.finish_dataset_publication_attempt(
                publication_id=publication_id,
                attempt_id=attempt_id,
                retryable=(
                    exhausted and should_retry_resource_exhaustion(ordinal)
                ),
                diagnostic=diagnostic,
            )
            return self.recover(publication_id)
        return self.recover(publication_id)

    def _build_candidate(
        self,
        publication: dict[str, object],
        objects: ObjectStoreStagePort,
    ) -> dict[str, object]:
        publisher = DatasetPublisher(
            self.metadata,
            objects,
            release_committer=lambda release, _key: (release, True),
        )
        kind = str(publication["kind"])
        parameters = publication["parameters"]
        if not isinstance(parameters, dict):
            raise InvalidFixtureError("Dataset Publication parameters are invalid")
        key = str(publication["idempotency_key"])
        if kind == "fixture_bootstrap":
            release, _created = publisher.bootstrap(
                key,
                str(parameters["fixture"]),
            )
            return release
        if kind == "fixture_increment":
            corrections = parameters["corrections"]
            if not isinstance(corrections, list):
                raise InvalidFixtureError("fixture corrections are invalid")
            release, _created = publisher.publish_fixture_increment(
                key,
                new_sessions=int(parameters["new_sessions"]),
                corrections=[
                    {str(field): str(value) for field, value in item.items()}
                    for item in corrections
                    if isinstance(item, dict)
                ],
            )
            return release
        if not self.metadata.source_authorization_is_authorized():
            raise DatasetPublicationRequestError(
                "SOURCE_AUTHORIZATION_REQUIRED",
                publication_request_error_message(
                    "SOURCE_AUTHORIZATION_REQUIRED"
                ),
            )
        if self.settings is None or not self.settings.tushare_token:
            raise DatasetPublicationRequestError(
                "TOKEN_MISSING",
                "Tushare token is not configured",
            )
        adapter = TushareAdapter(
            token=self.settings.tushare_token,
            transport=self.tushare_transport,
        )
        as_of = date.fromisoformat(str(parameters["as_of"]))
        if kind == "live_bootstrap":
            adapter.preflight()
            source, canonical = normalize_tushare_snapshot(
                adapter.collect_bootstrap_snapshot(as_of)
            )
            release, _created = publisher.bootstrap_documents(
                key,
                source=source,
                canonical=canonical,
                source_kind="source_tushare",
                source_schema="tushare-v1",
            )
            return release
        predecessor = self.metadata.latest_dataset_release()
        if predecessor is None:
            raise InvalidFixtureError("live Bootstrap must be published first")
        schemas = predecessor.get("schemas")
        if not isinstance(schemas, list) or not any(
            isinstance(item, dict) and item.get("family") == "source_tushare"
            for item in schemas
        ):
            raise InvalidFixtureError(
                "live increment requires a live Dataset Release predecessor"
            )
        canonical = publisher.materialize_canonical_tail(predecessor, 20)
        instruments = canonical.get("instruments")
        calendar = canonical.get("research_calendar")
        if (
            not isinstance(instruments, list)
            or not isinstance(calendar, list)
            or not calendar
        ):
            raise InvalidFixtureError("predecessor canonical data is incomplete")
        snapshot = adapter.collect_incremental_snapshot(
            last_session=str(calendar[-1]),
            known_ts_codes={
                str(item["ts_code"])
                for item in instruments
                if isinstance(item, dict)
            },
            as_of=as_of,
        )
        source, canonical_delta = normalize_tushare_increment(
            snapshot,
            canonical,
        )
        release, _created = publisher.publish_increment_documents(
            key,
            source=source,
            canonical_delta=canonical_delta,
            source_schema="tushare-v1",
        )
        return release

    def recover(self, publication_id: str) -> dict[str, object]:
        with self.objects.publication_guard(publication_id):
            current = self.metadata.dataset_publication(publication_id)
            if current is None:
                raise KeyError(publication_id)
            digest = current.get("result_manifest_sha256")
            self.objects.recover_staged_publication(
                publication_id,
                committed_manifest_sha256=(
                    str(digest)
                    if current["status"] == "succeeded"
                    and isinstance(digest, str)
                    else None
                ),
            )
            return current


def publication_audit_event(
    *,
    actor: str,
    occurred_at: str,
    outcome: str,
    reason_code: str | None,
    subject_id: str,
    request_version: str,
    kind: str,
    trigger_kind: str,
) -> dict[str, object]:
    return {
        "id": f"audit_{uuid4().hex}",
        "occurred_at": occurred_at,
        "actor": actor,
        "action": "dataset_publication.request",
        "outcome": outcome,
        "reason_code": reason_code,
        "subject_type": "dataset_publication",
        "subject_id": subject_id,
        "details": {
            "kind": kind,
            "request_version": request_version,
            "trigger_kind": trigger_kind,
        },
    }


def publication_request_error_message(reason_code: str) -> str:
    return {
        "OPERATOR_ACTOR_REQUIRED": "operator actor is required",
        "IDEMPOTENCY_KEY_REQUIRED": "idempotency key is required",
        "DATASET_PUBLICATION_VERSION_UNSUPPORTED": (
            "Dataset Publication request version is unsupported"
        ),
        "DATASET_PUBLICATION_KIND_UNSUPPORTED": (
            "Dataset Publication kind is unsupported"
        ),
        "DATASET_PUBLICATION_PARAMETERS_INVALID": (
            "Dataset Publication parameters are invalid"
        ),
        "SOURCE_AUTHORIZATION_REQUIRED": (
            "hosted shared Tushare use requires an accepted Operator declaration"
        ),
    }[reason_code]


def local_source_authorization_gate(metadata) -> SourceAuthorizationGate:
    class MetadataGate:
        def is_authorized(self) -> bool:
            return bool(metadata.source_authorization_is_authorized())

    return MetadataGate()


__all__ = [
    "DatasetPublicationRequestError",
    "DatasetPublicationRequestService",
    "DatasetPublicationService",
    "local_source_authorization_gate",
]
