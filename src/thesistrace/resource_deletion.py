from datetime import UTC, datetime

from thesistrace.ports import (
    ControlMetadataPort,
    ObjectStorePort,
    WorkingCachePort,
)


class ResourceDeletionError(RuntimeError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class ResourceDeletionService:
    def __init__(
        self,
        metadata: ControlMetadataPort,
        objects: ObjectStorePort,
        cache: WorkingCachePort,
    ) -> None:
        self.metadata = metadata
        self.objects = objects
        self.cache = cache

    def delete_research_run(
        self,
        run_id: str,
        *,
        actor: str,
    ) -> dict[str, object]:
        return self._delete("research_run", run_id, actor=actor)

    def delete_daily_track(
        self,
        track_id: str,
        *,
        actor: str,
    ) -> dict[str, object]:
        return self._delete("daily_track", track_id, actor=actor)

    def _delete(
        self,
        resource_kind: str,
        resource_id: str,
        *,
        actor: str,
    ) -> dict[str, object]:
        try:
            with self.metadata.storage_mutation_fence():
                tombstone = self.metadata.request_resource_deletion(
                    resource_kind=resource_kind,
                    resource_id=resource_id,
                    actor=actor,
                    deleted_at=datetime.now(UTC).isoformat(),
                )
        except ValueError as error:
            reason_code = str(error)
            if reason_code == "RESOURCE_NOT_TERMINAL":
                message = "only terminal private resources can be deleted"
            elif reason_code == "RESOURCE_RETAINED":
                message = "resource is retained by a DailyTrack"
            elif reason_code == "RESOURCE_STORAGE_UNINDEXED":
                message = "resource storage index requires reconciliation"
            else:
                raise
            raise ResourceDeletionError(reason_code, message) from error
        if tombstone is None:
            raise ResourceDeletionError(
                "RESOURCE_NOT_FOUND",
                "private resource not found",
            )
        self.reconcile_pending(tombstone_id=str(tombstone["id"]))
        return tombstone

    def reconcile_pending(
        self,
        *,
        tombstone_id: str | None = None,
    ) -> list[dict[str, str]]:
        outcomes: list[dict[str, str]] = []
        for job in self.metadata.pending_resource_cleanups():
            current_id = str(job["tombstone_id"])
            if tombstone_id is not None and current_id != tombstone_id:
                continue
            try:
                with self.metadata.storage_mutation_fence():
                    daily_track_id = job.get("daily_track_id")
                    fencing_token = job.get("fencing_token")
                    if daily_track_id is not None and fencing_token is not None:
                        self.cache.advance_fence(
                            str(daily_track_id),
                            int(fencing_token),
                            stopped=True,
                        )
                        self.cache.delete_if_not_newer(
                            str(daily_track_id),
                            int(fencing_token),
                        )
                    for object_key in (
                        self.metadata.resource_cleanup_candidates(current_id)
                    ):
                        self.objects.delete_storage_object(object_key)
                    self.metadata.complete_resource_cleanup(
                        current_id,
                        datetime.now(UTC).isoformat(),
                    )
            except Exception as error:
                self.metadata.fail_resource_cleanup(current_id, str(error))
                outcomes.append(
                    {"tombstone_id": current_id, "status": "pending"}
                )
                continue
            outcomes.append(
                {"tombstone_id": current_id, "status": "completed"}
            )
        return outcomes
