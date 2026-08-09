from __future__ import annotations

from fastapi.testclient import TestClient

from thesistrace.adapters.fixture_data import FixtureDataSource
from thesistrace.data.source import CollectionPlan, DataSource
from thesistrace.data.validation import validate_release_batch
from thesistrace.publication import JsonPayload
from thesistrace.publication.serialization import canonical_json_bytes


def publish_fixture_release(
    client: TestClient,
    *,
    source: DataSource | None = None,
) -> dict[str, object]:
    """Publish canonical fixture data through a test-only product-state factory."""
    runtime = client.app.state.core_runtime
    with runtime.database.transaction() as transaction:
        predecessor = transaction.execute(
            """
            SELECT release.id, release.session_end
            FROM data.state AS state
            LEFT JOIN data.releases AS release
              ON release.id = state.latest_release_id
            WHERE state.singleton = 1
            """
        ).fetchone()
    if predecessor is None:
        raise RuntimeError("Data state is not initialized")
    predecessor_id = None if predecessor["id"] is None else str(predecessor["id"])
    plan = (
        CollectionPlan.bootstrap()
        if predecessor_id is None
        else CollectionPlan.incremental(
            str(predecessor["session_end"]),
            runtime.data.load_canonical(predecessor_id),
        )
    )
    batch = (source or FixtureDataSource()).collect(plan)
    validate_release_batch(
        batch,
        predecessor_session=(
            None if predecessor_id is None else str(predecessor["session_end"])
        ),
    )
    calendar = batch.canonical["research_calendar"]
    assert isinstance(calendar, list)
    appended_sessions = calendar
    if predecessor_id is not None:
        predecessor_index = calendar.index(str(predecessor["session_end"]))
        appended_sessions = calendar[predecessor_index + 1 :]
    if not appended_sessions:
        raise RuntimeError("Fixture Release appended no Research Sessions")
    provenance = {
        "canonical_contract": "canonical-eod-v1",
        "collection_kind": batch.collection_kind,
        "covered_session_range": {
            "start": batch.covered_session_range[0],
            "end": batch.covered_session_range[1],
        },
        "appended_session_range": {
            "start": str(appended_sessions[0]),
            "end": str(appended_sessions[-1]),
        },
        "correction_change_set": [],
        "predecessor_id": predecessor_id,
        "source_name": batch.source_name,
    }
    prepared = runtime.publication.prepare(
        kind="data.release",
        payloads={
            "canonical": JsonPayload(batch.canonical),
            "collection_lineage": JsonPayload(batch.source_lineage),
        },
        provenance=provenance,
    )
    release_id = f"dsr_{prepared.manifest_sha256[:24]}"
    with runtime.database.transaction() as transaction:
        current = transaction.execute(
            """
            SELECT latest_release_id
            FROM data.state
            WHERE singleton = 1
            FOR UPDATE
            """
        ).fetchone()
        if current is None or current["latest_release_id"] != predecessor_id:
            raise RuntimeError("Fixture Release Head changed during publication")
        published = runtime.publication.record(transaction, prepared)
        transaction.execute(
            """
            INSERT INTO data.releases (
                id, predecessor_id, manifest_sha256, source_name,
                collection_kind, canonical_schema, session_start,
                session_end, session_count, appended_session_start,
                appended_session_end, provenance_version
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 2)
            """,
            (
                release_id,
                predecessor_id,
                published.manifest_sha256,
                batch.source_name,
                batch.collection_kind,
                batch.canonical["schema_version"],
                batch.covered_session_range[0],
                batch.covered_session_range[1],
                len(calendar),
                str(appended_sessions[0]),
                str(appended_sessions[-1]),
            ),
        )
        for field in batch.canonical["field_catalog"]:
            field_id = str(field["field_id"])
            transaction.execute(
                """
                INSERT INTO data.fields (field_id, definition)
                VALUES (%s, %s)
                ON CONFLICT (field_id) DO NOTHING
                """,
                (field_id, canonical_json_bytes(field).decode()),
            )
            transaction.execute(
                "INSERT INTO data.release_fields (release_id, field_id) VALUES (%s, %s)",
                (release_id, field_id),
            )
        transaction.execute(
            """
            UPDATE data.state
            SET status = 'idle', latest_update_outcome = 'published',
                latest_release_id = %s, updated_at = now()
            WHERE singleton = 1
            """,
            (release_id,),
        )
    return latest_fixture_release(client)


def latest_fixture_release(client: TestClient) -> dict[str, object] | None:
    runtime = client.app.state.core_runtime
    with runtime.database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT release.id, release.predecessor_id, release.session_count,
                   release.session_start, release.session_end
            FROM data.state AS state
            JOIN data.releases AS release ON release.id = state.latest_release_id
            WHERE state.singleton = 1
            """
        ).fetchone()
    if row is None:
        return None
    return {
        "id": str(row["id"]),
        "predecessor_id": (
            None if row["predecessor_id"] is None else str(row["predecessor_id"])
        ),
        "session_count": int(row["session_count"]),
        "covered_session_range": {
            "start": str(row["session_start"]),
            "end": str(row["session_end"]),
        },
    }
