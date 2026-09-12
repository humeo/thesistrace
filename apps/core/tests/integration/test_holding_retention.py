from datetime import timedelta
from uuid import uuid4

import pytest

from thesistrace.entrypoints.runtime import open_core_runtime
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.publication import JsonPayload
from thesistrace.publication.holding_retention import HOLDING_KIND, HoldingRetention


@pytest.fixture
def holdings_runtime(core_settings):
    initialize_core(core_settings.database_url)
    with open_core_runtime(core_settings) as runtime:
        yield runtime


def _record(runtime, retention, owner, *, payload=None):
    unit_id = "holdings-" + uuid4().hex
    prepared = runtime.publication.prepare(
        kind=HOLDING_KIND,
        payloads={"daily_holdings": JsonPayload(
            payload if payload is not None else {"sessions": ["2026-01-05"], "parts": []},
        )},
        provenance={"holding_unit_id": unit_id},
    )
    with runtime.database.transaction() as tx:
        row = retention.record(
            tx, unit_id=unit_id, researcher_id=owner, source_kind="research_run",
            source_id="run-" + uuid4().hex, sessions=["2026-01-05"], prepared=prepared,
        )
    return unit_id, row


def test_holding_retention_renews_only_successful_details_and_expires_logically(holdings_runtime):
    runtime = holdings_runtime
    retention = HoldingRetention(runtime.database, runtime.publication)
    owner = uuid4()
    unit_id, published = _record(runtime, retention, owner)
    assert published["expires_at"] - published["published_at"] == timedelta(days=7)
    assert retention.inspect(uuid4(), unit_id) is None
    # Position the publication six days before the server clock, retaining the original interval.
    with runtime.database.transaction() as tx:
        tx.execute(
            "UPDATE publication.holding_units SET published_at = published_at - interval '6 days', "
            "expires_at = expires_at - interval '6 days' WHERE id = %s", (unit_id,),
        )
    before = retention.inspect(owner, unit_id)
    assert retention.inspect(owner, unit_id) == before

    def failed_read(tx, reference):
        raise ValueError("failed object verification")

    with pytest.raises(ValueError, match="verification"):
        retention.read_detail(owner, unit_id, failed_read)
    assert retention.inspect(owner, unit_id) == before
    metadata, result = retention.read_detail(
        owner, unit_id, lambda tx, ref: runtime.publication.read_selected_in_transaction(
            tx, ref, frozenset({"daily_holdings"}),
        ),
    )
    assert result.payloads["daily_holdings"].content
    assert metadata["expires_at"] - metadata["last_read_at"] == timedelta(days=7)
    assert timedelta(days=13) <= metadata["expires_at"] - before["published_at"] < timedelta(
        days=13, minutes=1,
    )
    with runtime.database.transaction() as tx:
        tx.execute(
            "UPDATE publication.holding_units "
            "SET published_at = clock_timestamp() - interval '8 days', "
            "expires_at = clock_timestamp() - interval '1 second' WHERE id = %s", (unit_id,),
        )
    assert retention.inspect(owner, unit_id)["status"] == "expired"
    metadata, body = retention.read_detail(owner, unit_id, failed_read)
    assert metadata["status"] == "expired" and body is None
    assert retention.expire_once() >= 1
    assert retention.inspect(owner, unit_id)["status"] == "expired"
    with runtime.database.transaction() as tx:
        row = tx.execute(
            "SELECT manifest_sha256, expired_at FROM publication.holding_units WHERE id = %s",
            (unit_id,),
        ).fetchone()
    assert row["manifest_sha256"] is None and row["expired_at"] is not None


def test_holding_expiry_maintenance_preserves_shared_permanent_bytes(
    holdings_runtime, core_settings, rustfs_admin,
):
    from thesistrace.publication import PublicationMaintenance

    runtime = holdings_runtime
    retention = HoldingRetention(runtime.database, runtime.publication)
    owner = uuid4()
    unit_id, row = _record(runtime, retention, owner)
    permanent = runtime.publication.prepare(
        kind="research.result",
        payloads={"daily_holdings": JsonPayload({"sessions": ["2026-01-05"], "parts": []})},
        provenance={"run_id": "permanent-" + uuid4().hex},
    )
    with runtime.database.transaction() as tx:
        permanent_ref = runtime.publication.record(tx, permanent)
        tx.execute(
            "UPDATE publication.holding_units SET published_at = now() - interval '8 days', "
            "expires_at = now() - interval '1 day' WHERE id = %s", (unit_id,),
        )
        tx.execute(
            "UPDATE publication.maintenance_state SET next_due_at = "
            "CASE WHEN job = 'holding_expiry' THEN now() ELSE now() + interval '1 day' END"
        )
    maintenance = PublicationMaintenance(
        runtime.database, rustfs_admin, bucket=core_settings.s3_bucket,
    )
    result = maintenance.run_once()
    assert result["job"] == "holding_expiry" and result["processed"] == 1
    assert retention.inspect(owner, unit_id)["status"] == "expired"
    assert runtime.publication.read(permanent_ref).payloads["daily_holdings"].content
    with runtime.database.transaction() as tx:
        assert tx.execute(
            "SELECT 1 FROM publication.manifests WHERE sha256 = %s", (row["manifest_sha256"],),
        ).fetchone() is None
    # Physical collection must still leave the permanent reference readable.
    while runtime.publication.collect_one_pending_deletion():
        pass
    assert runtime.publication.read(permanent_ref).payloads["daily_holdings"].content


def test_holding_retention_admitted_read_wins_expiry_and_units_remain_independent(
    holdings_runtime, monkeypatch,
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    runtime = holdings_runtime
    retention = HoldingRetention(runtime.database, runtime.publication)
    owner = uuid4()
    unit_id, _ = _record(runtime, retention, owner)
    other_id, _ = _record(runtime, retention, owner)
    other_before = retention.inspect(owner, other_id)
    with runtime.database.transaction() as tx:
        deadline = tx.execute(
            "UPDATE publication.holding_units "
            "SET published_at = clock_timestamp() - interval '8 days', "
            "expires_at = clock_timestamp() - interval '1 second' "
            "WHERE id = %s RETURNING expires_at", (unit_id,),
        ).fetchone()["expires_at"]
    real_unit = retention._unit

    def admitted_before_deadline(tx, researcher_id, requested_unit, *, lock):
        row = real_unit(tx, researcher_id, requested_unit, lock=lock)
        # Control only this reader's admission clock. The real database already
        # considers the row due, so collection must skip its held lock, independent
        # of thread scheduling speed. Renewal still uses the actual database clock.
        if lock and requested_unit == unit_id and row is not None:
            row["observed_at"] = deadline - timedelta(seconds=1)
        return row

    monkeypatch.setattr(retention, "_unit", admitted_before_deadline)
    entered, release = Event(), Event()

    def slow_read(tx, reference):
        entered.set()
        assert release.wait(5), "test did not release the admitted reader"
        return runtime.publication.read_selected_in_transaction(
            tx, reference, frozenset({"daily_holdings"}),
        ).payloads["daily_holdings"].content

    with ThreadPoolExecutor(max_workers=1) as executor:
        reader = executor.submit(retention.read_detail, owner, unit_id, slow_read)
        try:
            assert entered.wait(3)
            retention.expire_once()
            with runtime.database.transaction() as tx:
                row = tx.execute(
                    "SELECT manifest_sha256 FROM publication.holding_units WHERE id = %s",
                    (unit_id,),
                ).fetchone()
            assert row["manifest_sha256"] is not None
        finally:
            release.set()
        metadata, content = reader.result(timeout=5)
    assert metadata["status"] == "available" and content
    assert metadata["expires_at"] > deadline + timedelta(days=6)
    assert retention.inspect(owner, other_id) == other_before


def test_holding_retention_delete_failure_retries_without_reviving_expired_details(
    holdings_runtime, core_settings, rustfs_admin,
):
    from time import monotonic

    from botocore.stub import Stubber

    from thesistrace.publication import Publication, PublicationUnavailableError

    runtime = holdings_runtime
    retention = HoldingRetention(runtime.database, runtime.publication)
    owner = uuid4()
    unit_id, published = _record(
        runtime, retention, owner, payload={"sessions": ["2026-01-05"], "probe": uuid4().hex},
    )
    with runtime.database.transaction() as tx:
        hashes = [row["object_sha256"] for row in tx.execute(
            "SELECT object_sha256 FROM publication.manifest_objects WHERE manifest_sha256 = %s",
            (published["manifest_sha256"],),
        ).fetchall()]
        tx.execute(
            "UPDATE publication.holding_units SET published_at = now() - interval '8 days', "
            "expires_at = now() - interval '1 second' WHERE id = %s", (unit_id,),
        )
    started = monotonic()
    assert retention.expire_once() >= 1
    expired = retention.inspect(owner, unit_id)
    collector = Publication(runtime.database, rustfs_admin, bucket=core_settings.s3_bucket)
    with Stubber(rustfs_admin) as failure:
        failure.add_client_error("delete_object", service_error_code="ServiceUnavailable",
                                 http_status_code=503)
        with pytest.raises(PublicationUnavailableError):
            collector.collect_one_pending_deletion()
    with runtime.database.transaction() as tx:
        assert tx.execute(
            "SELECT count(*) AS count FROM publication.object_deletions "
            "WHERE object_sha256 = ANY(%s)", (hashes,),
        ).fetchone()["count"] > 0
    assert retention.read_detail(owner, unit_id, lambda *_: pytest.fail("expired I/O")) == (
        expired, None,
    )
    # Restore the actual S3 client; a successful retry must remove the same queued objects.
    while collector.collect_one_pending_deletion():
        assert monotonic() - started < 10, "bounded fixture cleanup did not finish"
    with runtime.database.transaction() as tx:
        assert tx.execute(
            "SELECT count(*) AS count FROM publication.objects WHERE sha256 = ANY(%s)",
            (hashes,),
        ).fetchone()["count"] == 0
    assert retention.inspect(owner, unit_id) == expired
    print(f"holding expiry + injected failure + physical recovery: {monotonic() - started:.3f}s")


def test_holding_retention_foreign_owner_cannot_read_or_extend(holdings_runtime):
    runtime = holdings_runtime
    retention = HoldingRetention(runtime.database, runtime.publication)
    owner = uuid4()
    unit_id, published = _record(runtime, retention, owner)
    before = retention.inspect(owner, unit_id)
    foreign = uuid4()
    assert retention.read_detail(foreign, unit_id, lambda *_: pytest.fail("foreign I/O")) is None
    units, cursor, recorded = retention.list_units(
        foreign, sources=[("research_run", published["source_id"])], boundary="2026-01-05",
    )
    assert units == [] and cursor is None and recorded is False
    assert retention.inspect(owner, unit_id) == before
    # A filter that matches no dates differs from an entirely unrecorded resource.
    units, cursor, recorded = retention.list_units(
        owner, sources=[("research_run", published["source_id"])], boundary="2026-01-05",
        start_session="2026-01-06",
    )
    assert units == [] and cursor is None and recorded is True
    assert retention.inspect(owner, unit_id) == before


def test_holding_retention_uncommitted_publication_is_collectable(
    holdings_runtime, core_settings, rustfs_admin,
):
    from botocore.exceptions import ClientError
    from test_publication_records import _find_key_with_content

    from thesistrace.publication import PublicationMaintenance
    from thesistrace.publication.serialization import canonical_json_bytes

    runtime = holdings_runtime
    retention = HoldingRetention(runtime.database, runtime.publication)
    owner = uuid4()
    valid_id, _ = _record(runtime, retention, owner)
    failed_id = "holdings-" + uuid4().hex
    payload = {"sessions": ["2026-01-05"], "parts": [], "probe": failed_id}
    prepared = runtime.publication.prepare(
        kind=HOLDING_KIND, payloads={"daily_holdings": JsonPayload(payload)},
        provenance={"holding_unit_id": failed_id},
    )
    with pytest.raises(RuntimeError, match="publication rollback"):
        with runtime.database.transaction() as tx:
            retention.record(
                tx, unit_id=failed_id, researcher_id=owner, source_kind="research_run",
                source_id="cancelled-run", sessions=["2026-01-05"], prepared=prepared,
            )
            raise RuntimeError("publication rollback")
    assert retention.inspect(owner, failed_id) is None
    key = _find_key_with_content(rustfs_admin, core_settings.s3_bucket,
                                 canonical_json_bytes(payload))
    # Move only the isolated scan's cutoff forward; production grace is unchanged.
    with runtime.database.transaction() as tx:
        tx.execute(
            "UPDATE publication.maintenance_state SET next_due_at = now() + interval '1 day'"
        )
        tx.execute(
            "UPDATE publication.maintenance_state SET next_due_at = now(), last_key = '', "
            "cutoff = now() + interval '5 minutes', sweep_started_at = now() "
            "WHERE job = 'orphan_scan'"
        )
    result = PublicationMaintenance(
        runtime.database, rustfs_admin, bucket=core_settings.s3_bucket,
    ).run_once()
    assert result["job"] == "orphan_scan" and result["deleted"] >= 1
    with pytest.raises(ClientError) as missing:
        rustfs_admin.head_object(Bucket=core_settings.s3_bucket, Key=key)
    assert missing.value.response["ResponseMetadata"]["HTTPStatusCode"] == 404
    metadata, bundle = retention.read_detail(
        owner, valid_id, lambda tx, ref: runtime.publication.read_selected_in_transaction(
            tx, ref, frozenset({"daily_holdings"}),
        ),
    )
    assert metadata["status"] == "available" and bundle.payloads["daily_holdings"].content
