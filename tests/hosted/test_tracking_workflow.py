import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from temporalio.exceptions import ApplicationError

from thesistrace.activity_contract import (
    MAX_AUTOMATIC_ACTIVITY_EXECUTIONS,
    MAX_RESOURCE_EXHAUSTION_EXECUTIONS,
)
from thesistrace.api import create_app
from thesistrace.config import Settings
from thesistrace.datasets import DatasetPublisher
from thesistrace.hosted import temporal_worker
from thesistrace.hosted.activity_policy import (
    resource_aware_activity_retry_policy,
)
from thesistrace.hosted.execution_relay import relay_once
from thesistrace.hosted.tracking_workflow import (
    TRACKING_TASK_QUEUE,
    tracking_advance_workflow_id,
    tracking_release_workflow_id,
)
from thesistrace.objects import ImmutableObjectStore
from thesistrace.research_runs import ResearchRunService
from thesistrace.runtime import build_runtime
from thesistrace.storage import MetadataStore
from thesistrace.tracking import (
    CorrectionImpactCache,
    DailyTrackingService,
)
from thesistrace.working_cache import WorkingCacheStore


def definition() -> dict[str, object]:
    return {
        "title": "Hosted Tracking",
        "hypothesis": "过去 20 日上涨的股票未来收益更高。",
        "dataset_release": "latest",
        "universe": "top300",
        "alpha": {"expression": "pct_change($close_adj, 20)"},
        "neutralization": "industry",
        "strategy": {
            "holdings_count": 30,
            "rebalance_interval": 5,
            "initial_cash_cny": "10000000",
            "execution": "next_open_full_fill",
        },
        "costs": {
            "commission_rate_all_in": "0.0003",
            "commission_min_cny": "5",
            "stamp_duty_sell_rate": "0.0005",
            "transfer_fee_rate": "0.00001",
        },
        "risk_free_rate": "0",
    }


def prepare_active_track(
    tmp_path: Path,
) -> tuple[Settings, DatasetPublisher, DailyTrackingService, dict[str, object]]:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
        working_cache_root=tmp_path / "working-cache",
    )
    with TestClient(create_app(settings)) as client:
        client.post(
            "/api/v1/dataset-releases/bootstrap",
            headers={"Idempotency-Key": "tracking-workflow-seed"},
            json={"fixture": "v1"},
        ).raise_for_status()
        draft = client.post(
            "/api/v1/research-definitions",
            json=definition(),
        ).json()
        run = client.post(
            f"/api/v1/research-definitions/{draft['id']}/runs",
            headers={"Idempotency-Key": "tracking-workflow-run"},
        ).json()["run"]
        metadata = MetadataStore(settings.metadata_path)
        objects = ImmutableObjectStore(settings.object_root)
        publisher = DatasetPublisher(metadata, objects)
        ResearchRunService(metadata, publisher, objects).execute(str(run["id"]))
        track = client.post(
            f"/api/v1/research-runs/{run['id']}/daily-tracks",
            headers={"Idempotency-Key": "tracking-workflow-activation"},
        ).json()
    return (
        settings,
        publisher,
        DailyTrackingService(
            metadata,
            publisher,
            objects,
            WorkingCacheStore(settings.working_cache_root),
        ),
        track,
    )


class NoopHeartbeat:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def checkpoint(self, _label: str) -> None:
        return None


def test_release_fanout_is_idempotent_and_advance_is_fenced_and_bounded(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings, publisher, tracking, track = prepare_active_track(tmp_path)
    first_release, _created = publisher.publish_fixture_increment(
        "tracking-workflow-first",
        new_sessions=1,
        corrections=[],
    )
    monkeypatch.setattr(
        temporal_worker,
        "settings_from_environment",
        lambda: settings,
    )
    monkeypatch.setattr(
        temporal_worker,
        "build_runtime",
        lambda _settings: build_runtime(settings),
    )
    monkeypatch.setattr(temporal_worker, "ActivityHeartbeat", NoopHeartbeat)

    request = {"release_id": str(first_release["id"])}
    first_fanout = temporal_worker.fanout_tracking_release(request)
    second_fanout = temporal_worker.fanout_tracking_release(request)

    assert first_fanout["active_track_count"] == 1
    assert second_fanout["advance_ids"] == first_fanout["advance_ids"]
    advance_id = str(first_fanout["advance_ids"][0])
    with MetadataStore(settings.metadata_path).connect() as connection:
        assert connection.execute(
            """
            SELECT COUNT(*) FROM tracking_advances
            WHERE daily_track_id = ? AND target_dataset_release_id = ?
            """,
            (track["id"], first_release["id"]),
        ).fetchone()[0] == 1
        assert connection.execute(
            """
            SELECT COUNT(*) FROM tracking_execution_outbox
            WHERE advance_id = ?
            """,
            (advance_id,),
        ).fetchone()[0] == 1

    first_claim = tracking._claim_advance(advance_id)
    assert first_claim is not None
    first_token = int(first_claim[1]["fencing_token"])
    redelivered = tracking.prepare_advance_redelivery(advance_id)
    assert redelivered["status"] == "blocked"
    assert redelivered["attempts"][0]["diagnostic"]["reason_code"] == (
        "ACTIVITY_REDELIVERED"
    )
    succeeded = tracking.execute_advance(advance_id)
    assert succeeded["status"] == "succeeded"
    assert int(succeeded["attempts"][-1]["fencing_token"]) == first_token + 1
    committed_head_id = tracking.get_track(str(track["id"]))["head_checkpoint_id"]
    assert tracking.fail_advance_delivery(advance_id)["status"] == "succeeded"
    assert (
        tracking.get_track(str(track["id"]))["head_checkpoint_id"]
        == committed_head_id
    )

    second_release, _created = publisher.publish_fixture_increment(
        "tracking-workflow-second",
        new_sessions=1,
        corrections=[],
    )
    second_advance_id = str(
        temporal_worker.fanout_tracking_release(
            {"release_id": str(second_release["id"])}
        )["advance_ids"][0]
    )
    manifest_paths = set(
        (settings.object_root / "manifests").glob("*.json")
    )
    payload_paths = set(
        (settings.object_root / "sha256").glob("*/*")
    )
    original_commit_advance = tracking.cache.commit_advance

    def fail_cache_commit(*_args, **_kwargs):
        raise RuntimeError("injected cache commit failure")

    monkeypatch.setattr(
        tracking.cache,
        "commit_advance",
        fail_cache_commit,
    )
    failed_publication = tracking.execute_advance(second_advance_id)
    assert failed_publication["status"] == "blocked"
    assert set(
        (settings.object_root / "manifests").glob("*.json")
    ) == manifest_paths
    assert set(
        (settings.object_root / "sha256").glob("*/*")
    ) == payload_paths
    assert not (
        settings.object_root / "staging" / second_advance_id
    ).exists()
    monkeypatch.setattr(
        tracking.cache,
        "commit_advance",
        original_commit_advance,
    )
    assert tracking.execute_advance(second_advance_id)["status"] == (
        "succeeded"
    )

    third_release, _created = publisher.publish_fixture_increment(
        "tracking-workflow-third",
        new_sessions=1,
        corrections=[],
    )
    third_advance_id = str(
        temporal_worker.fanout_tracking_release(
            {"release_id": str(third_release["id"])}
        )["advance_ids"][0]
    )
    prior_head_id = tracking.get_track(str(track["id"]))["head_checkpoint_id"]

    def exhaust(*_args, **_kwargs):
        raise MemoryError

    monkeypatch.setattr(tracking, "_calculate_advance", exhaust)
    first_exhaustion = tracking.execute_advance(third_advance_id)
    second_exhaustion = tracking.execute_advance(third_advance_id)
    repeated = tracking.execute_advance(third_advance_id)

    assert first_exhaustion["status"] == "blocked"
    assert second_exhaustion["status"] == "failed"
    assert len(second_exhaustion["attempts"]) == 2
    assert len(repeated["attempts"]) == 2
    assert {
        attempt["diagnostic"]["reason_code"]
        for attempt in second_exhaustion["attempts"]
    } == {"RESOURCE_EXHAUSTED"}
    assert tracking.get_track(str(track["id"]))["head_checkpoint_id"] == prior_head_id


@pytest.mark.parametrize(
    ("attempt", "non_retryable"),
    [(1, False), (2, True)],
)
def test_fanout_resource_exhaustion_stops_after_two_activity_executions(
    monkeypatch: pytest.MonkeyPatch,
    attempt: int,
    non_retryable: bool,
) -> None:
    monkeypatch.setattr(
        temporal_worker,
        "settings_from_environment",
        lambda: (_ for _ in ()).throw(
            MemoryError("injected fanout exhaustion")
        ),
    )
    monkeypatch.setattr(
        temporal_worker.activity,
        "info",
        lambda: SimpleNamespace(attempt=attempt),
    )

    with pytest.raises(ApplicationError) as exhausted:
        temporal_worker.fanout_tracking_release(
            {"release_id": "release-1"}
        )

    assert exhausted.value.type == "RESOURCE_EXHAUSTED"
    assert exhausted.value.non_retryable is non_retryable
    assert (
        resource_aware_activity_retry_policy().maximum_attempts
        == MAX_RESOURCE_EXHAUSTION_EXECUTIONS
    )


def test_correction_fanout_does_not_materialize_complete_canonical_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings, publisher, tracking, track = prepare_active_track(tmp_path)
    root = publisher.metadata.latest_dataset_release()
    assert root is not None
    canonical = publisher.materialize_canonical(root)
    historical = canonical["prices"][0]
    correction, _created = publisher.publish_fixture_increment(
        "tracking-workflow-correction",
        new_sessions=1,
        corrections=[
            {
                "session": str(historical["session"]),
                "instrument_id": str(historical["instrument_id"]),
                "field": "open_raw",
                "value": str(
                    float(str(historical["open_raw"])) + 0.01
                ),
            }
        ],
    )
    monkeypatch.setattr(
        publisher,
        "materialize_canonical",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError(
                "correction fanout must not materialize complete Canonical data"
            )
        ),
    )
    monkeypatch.setattr(
        publisher,
        "research_calendar_window",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError(
                "correction fanout must not scan the complete Research Calendar"
            )
        ),
    )
    neighborhood_reads: list[tuple[int, int]] = []
    read_neighborhood = publisher.research_calendar_neighborhood

    def count_neighborhood_reads(*args, **kwargs):
        neighborhood_reads.append(
            (
                int(kwargs["preceding_sessions"]),
                int(kwargs["following_sessions"]),
            )
        )
        return read_neighborhood(*args, **kwargs)

    monkeypatch.setattr(
        publisher,
        "research_calendar_neighborhood",
        count_neighborhood_reads,
    )
    membership_reads = 0
    read_membership = publisher.liquidity_universe_membership

    def count_membership_reads(*args, **kwargs):
        nonlocal membership_reads
        membership_reads += 1
        return read_membership(*args, **kwargs)

    monkeypatch.setattr(
        publisher,
        "liquidity_universe_membership",
        count_membership_reads,
    )
    correction_cache = CorrectionImpactCache()
    assert tracking._corrections_affect_track(
        track,
        correction["correction_change_set"],
        correction,
        correction_cache=correction_cache,
    )
    assert tracking._corrections_affect_track(
        track,
        correction["correction_change_set"],
        correction,
        correction_cache=correction_cache,
    )
    assert membership_reads == 1

    advance = tracking.enqueue_toward(
        str(track["id"]),
        str(correction["id"]),
        correction_cache=correction_cache,
    )

    assert advance is not None
    assert advance["correction_boundary"] is not None
    assert membership_reads == 1
    assert neighborhood_reads
    assert max(max(bounds) for bounds in neighborhood_reads) <= 252


def test_multi_session_catchup_uses_frontier_state_and_retains_all_new_alpha(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _settings, publisher, tracking, track = prepare_active_track(tmp_path)
    first_gap_release, _created = publisher.publish_fixture_increment(
        "tracking-workflow-20-session-gap",
        new_sessions=20,
        corrections=[],
    )
    release, _created = publisher.publish_fixture_increment(
        "tracking-workflow-10-session-gap",
        new_sessions=10,
        corrections=[],
    )
    release["predecessor_id"] = track["activation_release_id"]
    with tracking.metadata.connect() as connection:
        connection.execute(
            """
            UPDATE dataset_releases
            SET manifest_json = ?
            WHERE id = ?
            """,
            (
                json.dumps(
                    release,
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                release["id"],
            ),
        )
    advance = tracking.enqueue_toward(
        str(track["id"]),
        str(release["id"]),
    )
    assert advance is not None
    raw_get_track = tracking.get_track
    monkeypatch.setattr(
        tracking,
        "get_track",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError(
                "ordinary Advance must not load complete Track history"
            )
        ),
    )
    canonical_window_sizes: list[int] = []
    read_window = publisher.materialize_canonical_window

    def record_canonical_window(*args, **kwargs):
        canonical = read_window(*args, **kwargs)
        canonical_window_sizes.append(
            len(canonical["research_calendar"])
        )
        return canonical

    monkeypatch.setattr(
        publisher,
        "materialize_canonical_window",
        record_canonical_window,
    )

    completed = tracking.execute_advance(str(advance["id"]))

    assert completed["status"] == "succeeded"
    updated = raw_get_track(str(track["id"]))
    assert updated is not None
    manifest = tracking.objects.read_json(
        str(updated["head"]["manifest_sha256"])
    )
    assert manifest["processed_session_count"] == 30
    assert manifest["processed_session_range"] == {
        "start": first_gap_release["appended_session_range"]["start"],
        "end": release["appended_session_range"]["end"],
    }
    assert (
        manifest["objects"]["strategy_daily_observations"][
            "row_count"
        ]
        == 30
    )
    assert len(tracking.cache.read_pending_alpha(str(track["id"]))) == 21
    assert len(canonical_window_sizes) == 2
    assert max(canonical_window_sizes) <= 252 + 25


def test_advance_rejects_more_than_252_sessions_before_canonical_calculation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _settings, publisher, tracking, track = prepare_active_track(tmp_path)
    release, _created = publisher.publish_fixture_increment(
        "tracking-workflow-over-limit",
        new_sessions=1,
        corrections=[],
    )
    advance = tracking.enqueue_toward(
        str(track["id"]),
        str(release["id"]),
    )
    assert advance is not None
    prior_head_id = str(track["head_checkpoint_id"])
    monkeypatch.setattr(
        publisher,
        "research_calendar_range",
        lambda *_args, **_kwargs: [
            f"session-{index:03d}"
            for index in range(253)
        ],
    )
    monkeypatch.setattr(
        publisher,
        "materialize_canonical_window",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError(
                "over-limit Advance must fail before Canonical calculation"
            )
        ),
    )

    completed = tracking.execute_advance(str(advance["id"]))

    assert completed["status"] == "failed"
    assert completed["attempts"][-1]["diagnostic"]["reason_code"] == (
        "TRACKING_ADVANCE_SESSION_LIMIT"
    )
    assert tracking.get_track(str(track["id"]))["head_checkpoint_id"] == (
        prior_head_id
    )


def test_release_fanout_activity_processes_at_most_one_bounded_page(
    monkeypatch,
) -> None:
    refs = [
        {"workspace_id": "workspace-1", "track_id": f"track-{index:03d}"}
        for index in range(101)
    ]

    class FakeMetadata:
        def active_daily_track_scan_bound(self):
            return refs[-1]

        def active_daily_track_refs(self, **options):
            assert options == {
                "after_workspace_id": None,
                "after_track_id": None,
                "through_workspace_id": "workspace-1",
                "through_track_id": "track-100",
                "limit": 101,
            }
            return refs

    class FakeTracking:
        def enqueue_toward(
            self,
            track_id: str,
            _release_id: str,
            **_options,
        ):
            return {"id": f"advance-{track_id}"}

    monkeypatch.setattr(
        temporal_worker,
        "settings_from_environment",
        lambda: object(),
    )
    monkeypatch.setattr(
        temporal_worker,
        "build_runtime",
        lambda _settings: SimpleNamespace(control_metadata=FakeMetadata()),
    )
    monkeypatch.setattr(
        temporal_worker,
        "_tracking_service",
        lambda _runtime: FakeTracking(),
    )
    monkeypatch.setattr(temporal_worker, "ActivityHeartbeat", NoopHeartbeat)

    page = temporal_worker.fanout_tracking_release({"release_id": "release-1"})

    assert page["active_track_count"] == 100
    assert len(page["advance_ids"]) == 100
    assert page["next_cursor"] == {
        "workspace_id": "workspace-1",
        "track_id": "track-099",
    }
    assert page["scan_upper_bound"] == refs[-1]


class RecordingTemporalClient:
    def __init__(self) -> None:
        self.starts: list[dict[str, object]] = []

    async def start_workflow(self, workflow, request, **options):
        self.starts.append(
            {
                "workflow": workflow,
                "request": request,
                "options": options,
            }
        )

    def get_workflow_handle(self, workflow_id: str):
        raise AssertionError(f"unexpected workflow handle: {workflow_id}")


class TrackingOutbox:
    def __init__(self) -> None:
        self.dispatched: list[str] = []

    def pending(self, *, limit: int):
        assert limit == 25
        return [
            {
                "outbox_id": "tracking-release-outbox:release-1",
                "workspace_id": None,
                "resource_kind": "tracking_release",
                "resource_id": "release-1",
            },
            {
                "outbox_id": "outbox-advance-1",
                "workspace_id": "workspace-1",
                "resource_kind": "tracking_advance",
                "resource_id": "advance-1",
            },
        ]

    def mark_dispatched(self, outbox_id: str) -> bool:
        self.dispatched.append(outbox_id)
        return True


def test_relay_starts_finite_tracking_workflows_with_stable_ids() -> None:
    client = RecordingTemporalClient()
    outbox = TrackingOutbox()

    assert asyncio.run(relay_once(client, outbox)) == 2

    assert [start["options"]["id"] for start in client.starts] == [
        tracking_release_workflow_id("release-1"),
        tracking_advance_workflow_id("advance-1"),
    ]
    assert {
        start["options"]["task_queue"] for start in client.starts
    } == {TRACKING_TASK_QUEUE}
    assert client.starts[0]["request"] == {"release_id": "release-1"}
    release_retry = client.starts[0]["options"]["retry_policy"]
    assert (
        release_retry.maximum_attempts
        == MAX_AUTOMATIC_ACTIVITY_EXECUTIONS
    )
    assert release_retry.non_retryable_error_types == [
        "RESOURCE_EXHAUSTED"
    ]
    assert client.starts[1]["request"] == {
        "workspace_id": "workspace-1",
        "advance_id": "advance-1",
    }
    assert outbox.dispatched == [
        "tracking-release-outbox:release-1",
        "outbox-advance-1",
    ]
