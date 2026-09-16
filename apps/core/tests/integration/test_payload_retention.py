from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from time import monotonic
from uuid import uuid4

import pytest

from thesistrace.entrypoints.runtime import open_core_runtime
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.publication import JsonPayload, PublicationVerificationError
from thesistrace.publication.payload_retention import PayloadRetention


@pytest.fixture
def runtime(core_settings):
    initialize_core(core_settings.database_url)
    with open_core_runtime(core_settings) as runtime:
        yield runtime


def record(runtime):
    prepared = runtime.publication.prepare(
        kind="research.result",
        provenance={"test": uuid4().hex},
        payloads={
            "strategy_orders": JsonPayload({"orders": [uuid4().hex]}),
            "strategy_summary": JsonPayload({"nav": 1.2}),
        },
    )
    with runtime.database.transaction() as tx:
        ref = runtime.publication.record(
            tx,
            prepared,
            expiring_payloads=frozenset({"strategy_orders"}),
        )
    return ref


def metadata(runtime, ref):
    with runtime.database.transaction() as tx:
        return tx.execute(
            "SELECT * FROM publication.payload_retention WHERE manifest_sha256 = %s",
            (ref.manifest_sha256,),
        ).fetchone()


def expire(runtime, ref):
    with runtime.database.transaction() as tx:
        tx.execute(
            "UPDATE publication.payload_retention SET published_at = now() - interval '8 days', "
            "expires_at = now() - interval '1 day' WHERE manifest_sha256 = %s",
            (ref.manifest_sha256,),
        )


def test_only_successful_detail_reads_renew_and_expiry_reclaims_only_diagnostics(runtime):
    ref = record(runtime)
    retention = PayloadRetention(runtime.database, runtime.publication)
    before = metadata(runtime, ref)
    assert (
        timedelta(days=7)
        <= before["expires_at"] - before["published_at"]
        < timedelta(
            days=7,
            seconds=1,
        )
    )
    expected = runtime.publication.read_selected(ref, frozenset({"strategy_summary"}))
    assert metadata(runtime, ref) == before

    def fail(tx):
        raise ValueError("corrupt payload")

    with pytest.raises(ValueError, match="corrupt"):
        retention.read_detail(ref, fail)
    assert metadata(runtime, ref) == before
    renewed, value = retention.read_detail(
        ref,
        lambda tx: runtime.publication.read_selected_in_transaction(
            tx, ref, frozenset({"strategy_orders"})
        ),
    )
    assert value.payloads["strategy_orders"].content
    assert renewed["expires_at"] - renewed["last_read_at"] == timedelta(days=7)
    expire(runtime, ref)
    expired, value = retention.read_detail(ref, fail)
    assert expired["status"] == "expired" and value is None
    with runtime.database.transaction() as tx:
        assert retention.expire_one_in_transaction(tx)
    while runtime.publication.collect_one_pending_deletion():
        pass
    assert runtime.publication.read_selected(ref, frozenset({"strategy_summary"})) == expected
    assert runtime.publication.payload_names(ref) == {"strategy_orders", "strategy_summary"}
    with pytest.raises(PublicationVerificationError, match="expired"):
        runtime.publication.read_selected(ref, frozenset({"strategy_orders"}))
    with runtime.database.transaction() as tx:
        assert (
            tx.execute(
                "SELECT 1 FROM publication.manifest_objects WHERE manifest_sha256 = %s "
                "AND logical_name = 'strategy_orders'",
                (ref.manifest_sha256,),
            ).fetchone()
            is None
        )
        runtime.publication.release_manifest_in_transaction(
            tx,
            ref.manifest_sha256,
            still_referenced=False,
        )
    assert metadata(runtime, ref) is None


def test_expiry_preserves_shared_bytes_and_serializes_with_detail_reads(runtime):
    ref = record(runtime)
    content = runtime.publication.read(ref).payloads["strategy_orders"].content
    import json

    copy = runtime.publication.prepare(
        kind="research.result",
        provenance={"test": uuid4().hex},
        payloads={"permanent": JsonPayload(json.loads(content))},
    )
    with runtime.database.transaction() as tx:
        shared = runtime.publication.record(tx, copy)
    retention = PayloadRetention(runtime.database, runtime.publication)
    started, finish = Event(), Event()
    with runtime.database.transaction() as tx:
        tx.execute(
            "UPDATE publication.payload_retention SET expires_at = "
            "clock_timestamp() + interval '1 second' WHERE manifest_sha256 = %s",
            (ref.manifest_sha256,),
        )

    def read(tx):
        started.set()
        assert finish.wait(10)
        return runtime.publication.read_selected_in_transaction(
            tx,
            ref,
            frozenset({"strategy_orders"}),
        )

    with ThreadPoolExecutor(2) as pool:
        future = pool.submit(retention.read_detail, ref, read)
        assert started.wait(10)
        try:
            deadline = monotonic() + 10
            while True:
                with runtime.database.transaction() as tx:
                    due = tx.execute(
                        "SELECT expires_at <= clock_timestamp() AS due "
                        "FROM publication.payload_retention WHERE manifest_sha256 = %s",
                        (ref.manifest_sha256,),
                    ).fetchone()["due"]
                if due:
                    break
                assert monotonic() < deadline
                Event().wait(0.02)
            with runtime.database.transaction() as tx:
                # A locked read is skipped instead of being deleted underneath the reader.
                assert not retention.expire_one_in_transaction(tx)
        finally:
            finish.set()
        assert future.result(timeout=10)[1].payloads["strategy_orders"].content == content
    expire(runtime, ref)
    with runtime.database.transaction() as tx:
        assert retention.expire_one_in_transaction(tx)
    while runtime.publication.collect_one_pending_deletion():
        pass
    assert runtime.publication.read(shared).payloads["permanent"].content == content
