"""Persistent tracking slots, shared by Web and MCP admission only."""

from uuid import UUID

from thesistrace._postgres import PostgresTransaction


class TrackingSelectionError(RuntimeError):
    def __init__(self, code: str, limit: int | None, selected: set[str]):
        super().__init__(code)
        self.code = code
        self.limit = limit
        self.selected = sorted(selected)


def admit_tracking_action(
    transaction: PostgresTransaction,
    researcher_id: UUID,
    track_id: str,
    limit: int | None,
    selected_track_ids: list[str] | None = None,
) -> None:
    transaction.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (f"daily_tracks.activation.capacity:{researcher_id}",),
    ).fetchone()
    rows = transaction.execute(
        "SELECT id, quota_selected FROM daily_tracks.tracks WHERE researcher_id=%s "
        "AND status IN ('active','blocked','stopping') ORDER BY id FOR UPDATE",
        (researcher_id,),
    ).fetchall()
    available = {row["id"] for row in rows}
    selected = {row["id"] for row in rows if row["quota_selected"]}
    if track_id not in available:
        return  # The existing lifecycle admission returns its normal state error.
    over_limit = limit is not None and len(selected) > limit
    desired = set(selected_track_ids) if selected_track_ids is not None else None
    if desired is not None:
        if (
            len(desired) != len(selected_track_ids)
            or not desired <= available
            or track_id not in desired
            or (limit is not None and len(desired) > limit)
        ):
            raise TrackingSelectionError("TRACK_SELECTION_INVALID", limit, selected)
        if over_limit:
            if not desired <= selected or len(desired) != limit:
                raise TrackingSelectionError("TRACK_SELECTION_INVALID", limit, selected)
        elif not selected <= desired:
            raise TrackingSelectionError("TRACK_SELECTION_LOCKED", limit, selected)
    elif over_limit:
        raise TrackingSelectionError("TRACK_SELECTION_REQUIRED", limit, selected)
    elif track_id not in selected:
        if limit is not None and len(selected) >= limit:
            raise TrackingSelectionError("TRACK_NOT_SELECTED", limit, selected)
        desired = selected | {track_id}
    if desired is not None:
        transaction.execute(
            "UPDATE daily_tracks.tracks SET quota_selected=(id=ANY(%s)) "
            "WHERE researcher_id=%s AND status IN ('active','blocked','stopping')",
            (sorted(desired), researcher_id),
        )


def tracking_usage(
    transaction: PostgresTransaction, researcher_id: UUID, limit: int | None
) -> dict:
    rows = transaction.execute(
        "SELECT id,quota_selected FROM daily_tracks.tracks WHERE researcher_id=%s "
        "AND status IN ('active','blocked','stopping') ORDER BY id",
        (researcher_id,),
    ).fetchall()
    selected = [row["id"] for row in rows if row["quota_selected"]]
    return dict(
        limit=limit,
        selected_track_ids=selected,
        selection_required=limit is not None and len(selected) > limit,
        retained_count=len(rows),
    )
