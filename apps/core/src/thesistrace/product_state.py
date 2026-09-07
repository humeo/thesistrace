from __future__ import annotations

from botocore.client import BaseClient

from thesistrace._postgres import PostgresDatabase

PRODUCT_STATE_COUNT_NAMES = (
    "research_runs",
    "research_attempts",
    "research_progress",
    "research_checkpoints",
    "research_admission_receipts",
    "research_cancel_receipts",
    "research_tracking_receipts",
    "research_batches",
    "research_batch_items",
    "research_batch_attempts",
    "research_batch_starting_claims",
    "research_batch_task_attempts",
    "research_batch_private_artifacts",
    "research_batch_progress",
    "research_batch_admission_receipts",
    "research_batch_cancel_receipts",
    "daily_tracks",
    "tracking_checkpoints",
    "tracking_progressions",
    "tracking_attempts",
    "tracking_states",
    "tracking_refresh_receipts",
    "tracking_retry_receipts",
    "tracking_stop_receipts",
    "publication_manifests",
    "publication_manifest_objects",
    "publication_objects",
    "publication_object_deletions",
    "generation_pins",
    "rustfs_product_objects",
)


def product_state_counts(
    database: PostgresDatabase,
    s3: BaseClient,
    *,
    bucket: str,
) -> dict[str, int]:
    with database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT
                (SELECT count(*) FROM research_runs.runs) AS research_runs,
                (SELECT count(*) FROM research_runs.attempts) AS research_attempts,
                (SELECT count(*) FROM research_runs.progress) AS research_progress,
                (SELECT count(*) FROM research_runs.execution_checkpoints)
                    AS research_checkpoints,
                (SELECT count(*) FROM research_runs.admission_requests)
                    AS research_admission_receipts,
                (SELECT count(*) FROM research_runs.cancel_receipts)
                    AS research_cancel_receipts,
                (SELECT count(*) FROM research_runs.start_tracking_receipts)
                    AS research_tracking_receipts,
                (SELECT count(*) FROM research_batches.batches)
                    AS research_batches,
                (SELECT count(*) FROM research_batches.items)
                    AS research_batch_items,
                (SELECT count(*) FROM research_batches.attempts)
                    AS research_batch_attempts,
                (SELECT count(*) FROM research_batches.starting_claims)
                    AS research_batch_starting_claims,
                (SELECT count(*) FROM research_batches.task_attempts)
                    AS research_batch_task_attempts,
                (SELECT count(*) FROM research_batches.private_alpha_factor_artifacts)
                    AS research_batch_private_artifacts,
                (SELECT count(*) FROM research_batches.progress)
                    AS research_batch_progress,
                (SELECT count(*) FROM research_batches.admission_receipts)
                    AS research_batch_admission_receipts,
                (SELECT count(*) FROM research_batches.cancel_receipts)
                    AS research_batch_cancel_receipts,
                (SELECT count(*) FROM daily_tracks.tracks) AS daily_tracks,
                (SELECT count(*) FROM daily_tracks.session_checkpoints)
                    AS tracking_checkpoints,
                (SELECT count(*) FROM daily_tracks.session_progressions)
                    AS tracking_progressions,
                (SELECT count(*) FROM daily_tracks.session_progression_attempts)
                    AS tracking_attempts,
                (SELECT count(*) FROM daily_tracks.session_tracking_states)
                    AS tracking_states,
                (SELECT count(*) FROM daily_tracks.refresh_receipts)
                    AS tracking_refresh_receipts,
                (SELECT count(*) FROM daily_tracks.retry_receipts)
                    AS tracking_retry_receipts,
                (SELECT count(*) FROM daily_tracks.stop_receipts)
                    AS tracking_stop_receipts,
                (SELECT count(*) FROM publication.manifests)
                    AS publication_manifests,
                (SELECT count(*) FROM publication.manifest_objects)
                    AS publication_manifest_objects,
                (SELECT count(*) FROM publication.objects) AS publication_objects,
                (SELECT count(*) FROM publication.object_deletions)
                    AS publication_object_deletions,
                (SELECT count(*) FROM data.generation_pins) AS generation_pins
            """
        ).fetchone()
    assert row is not None
    counts = {key: int(value) for key, value in row.items()}
    counts["rustfs_product_objects"] = _rustfs_product_object_count(s3, bucket)
    if tuple(counts) != PRODUCT_STATE_COUNT_NAMES:
        raise RuntimeError("Product State inventory is incomplete")
    return counts


def _rustfs_product_object_count(s3: BaseClient, bucket: str) -> int:
    bucket_names = {item["Name"] for item in s3.list_buckets().get("Buckets", [])}
    if bucket not in bucket_names:
        return 0
    count = 0
    continuation_token: str | None = None
    while True:
        arguments: dict[str, object] = {"Bucket": bucket}
        if continuation_token is not None:
            arguments["ContinuationToken"] = continuation_token
        page = s3.list_objects_v2(**arguments)
        count += len(page.get("Contents", []))
        if not page.get("IsTruncated"):
            return count
        continuation_token = str(page["NextContinuationToken"])
