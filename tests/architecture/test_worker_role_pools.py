from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from thesistrace.entrypoints.worker import (
    WorkerCapacity,
    WorkerCapacityError,
    WorkerConfiguration,
    WorkerRole,
    parse_worker_arguments,
    process_one_poll,
    validate_worker_capacity,
)


@dataclass
class _ProductQueue:
    resource_id: str
    has_work: bool
    calls: int = 0

    def process_next(self, *, on_claim=None, on_execution_event=None) -> bool:
        del on_execution_event
        self.calls += 1
        if self.has_work and on_claim is not None:
            on_claim(self.resource_id, f"attempt-{self.resource_id}")
        return self.has_work


@dataclass
class _PublicationMaintenance:
    calls: int = 0

    def collect_one_pending_deletion(self) -> bool:
        self.calls += 1
        return True


@dataclass
class _TrackingQueue(_ProductQueue):
    cache_calls: int = 0

    def reconcile_working_cache(self) -> int:
        self.cache_calls += 1
        return 1


def _configuration(role: WorkerRole) -> WorkerConfiguration:
    return WorkerConfiguration(
        role=role,
        capacity=WorkerCapacity(
            cpu_count=2,
            memory_bytes=2 * 1024**3,
            execution_memory_bytes=1536 * 1024**2,
            calculation_threads=2,
        ),
    )


@pytest.mark.parametrize("role", (WorkerRole.RESEARCH, WorkerRole.TRACKING))
def test_worker_role_is_required_and_frozen_by_argument_parsing(role: WorkerRole) -> None:
    with pytest.raises(SystemExit):
        parse_worker_arguments(["--once"])

    parsed = parse_worker_arguments(["--role", role.value, "--once"])

    assert parsed.configuration.role is role
    assert parsed.once is True


def test_research_worker_claims_only_one_research_run_and_skips_maintenance() -> None:
    research = _ProductQueue("run-1", True)
    tracking = _TrackingQueue("track-1", True)
    publication = _PublicationMaintenance()
    events: list[dict[str, object]] = []
    runtime = SimpleNamespace(
        research_runs=research,
        daily_tracks=tracking,
        publication=publication,
    )

    process_one_poll(runtime, _configuration(WorkerRole.RESEARCH), emit=events.append)

    assert research.calls == 1
    assert tracking.calls == 0
    assert publication.calls == 0
    assert tracking.cache_calls == 0
    assert events == [
        {
            "event": "worker_claim",
            "role": "research",
            "slot": 1,
            "resource_type": "ResearchRun",
            "resource_id": "run-1",
            "attempt_id": "attempt-run-1",
        }
    ]


def test_tracking_worker_claims_only_one_advance_and_skips_maintenance() -> None:
    research = _ProductQueue("run-1", True)
    tracking = _TrackingQueue("track-1", True)
    publication = _PublicationMaintenance()
    events: list[dict[str, object]] = []
    runtime = SimpleNamespace(
        research_runs=research,
        daily_tracks=tracking,
        publication=publication,
    )

    process_one_poll(runtime, _configuration(WorkerRole.TRACKING), emit=events.append)

    assert research.calls == 0
    assert tracking.calls == 1
    assert publication.calls == 0
    assert tracking.cache_calls == 0
    assert events[0]["resource_type"] == "TrackingAdvance"
    assert events[0]["resource_id"] == "track-1"


@pytest.mark.parametrize(
    ("role", "expected_cache_calls"),
    ((WorkerRole.RESEARCH, 0), (WorkerRole.TRACKING, 1)),
)
def test_idle_worker_reclaims_at_most_one_publication_and_only_tracking_caches(
    role: WorkerRole,
    expected_cache_calls: int,
) -> None:
    research = _ProductQueue("run-1", False)
    tracking = _TrackingQueue("track-1", False)
    publication = _PublicationMaintenance()
    runtime = SimpleNamespace(
        research_runs=research,
        daily_tracks=tracking,
        publication=publication,
    )

    process_one_poll(runtime, _configuration(role), emit=lambda _event: None)

    assert publication.calls == 1
    assert tracking.cache_calls == expected_cache_calls


def test_worker_capacity_rejects_smaller_cgroup_limits(tmp_path: Path) -> None:
    (tmp_path / "cpu.max").write_text("100000 100000\n")
    (tmp_path / "memory.max").write_text(f"{1024**3}\n")

    with pytest.raises(WorkerCapacityError, match="CPU"):
        validate_worker_capacity(_configuration(WorkerRole.RESEARCH), tmp_path)


def test_worker_capacity_rejects_smaller_cgroup_memory_limit(tmp_path: Path) -> None:
    (tmp_path / "cpu.max").write_text("200000 100000\n")
    (tmp_path / "memory.max").write_text(f"{1024**3}\n")

    with pytest.raises(WorkerCapacityError, match="memory"):
        validate_worker_capacity(_configuration(WorkerRole.TRACKING), tmp_path)


def test_worker_capacity_accepts_matching_2c2g_cgroup(tmp_path: Path) -> None:
    (tmp_path / "cpu.max").write_text("200000 100000\n")
    (tmp_path / "memory.max").write_text(f"{2 * 1024**3}\n")

    actual = validate_worker_capacity(_configuration(WorkerRole.TRACKING), tmp_path)

    assert actual.cpu_count == 2
    assert actual.memory_bytes == 2 * 1024**3
