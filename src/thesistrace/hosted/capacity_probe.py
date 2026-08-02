import argparse
import asyncio
import json
import math
import resource
import sys
import threading
import time
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from temporalio.client import Client
from temporalio.service import RPCError

from thesistrace.bounded_research import (
    calculate_bounded_research,
    load_columnar_research_window,
)
from thesistrace.config import settings_from_environment
from thesistrace.datasets import DatasetPublisher
from thesistrace.hosted.capacity_corpus import (
    maximum_definition,
    publish_capacity_corpus,
    publish_capacity_increment,
)
from thesistrace.hosted.compute_dispatch import COMPUTE_WORKFLOW_TASK_QUEUE
from thesistrace.hosted.dataset_publication_workflow import (
    DATASET_PUBLICATION_TASK_QUEUE,
)
from thesistrace.objects import ImmutableObjectStore
from thesistrace.ports import LocalWorkerDispatch
from thesistrace.result_objects import publish_compact_result_objects
from thesistrace.runtime import RuntimePorts, build_runtime
from thesistrace.storage import MetadataStore
from thesistrace.working_cache import WorkingCacheStore

RESULT_RETRY_SECONDS = 2.0


class WorkflowResultHandle(Protocol):
    async def result(self) -> dict[str, object]: ...


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-root", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prepare")
    commands.add_parser("publish-increment")
    worker = commands.add_parser("worker")
    worker.add_argument("--release-id")
    scenario = commands.add_parser("scenario")
    scenario.add_argument("--temporal-address", default="temporal:7233")
    scenario.add_argument("--namespace", default="thesistrace")
    return parser


def main() -> None:
    arguments = build_parser().parse_args()
    if arguments.command == "scenario":
        print(
            json.dumps(
                asyncio.run(
                    run_scenario(
                        temporal_address=arguments.temporal_address,
                        namespace=arguments.namespace,
                    )
                ),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return
    runtime = _runtime(arguments.local_root)
    datasets = DatasetPublisher(
        runtime.control_metadata,
        runtime.objects,
    )
    if arguments.command == "prepare":
        release, created = publish_capacity_corpus(
            datasets,
            idempotency_key="capacity-qualification-top3000-v1",
        )
        print(
            json.dumps(
                {"created": created, "release_id": release["id"]},
                sort_keys=True,
            )
        )
        return
    if arguments.command == "publish-increment":
        release, created = publish_capacity_increment(
            datasets,
            idempotency_key="capacity-qualification-increment-v1",
        )
        print(
            json.dumps(
                {"created": created, "release_id": release["id"]},
                sort_keys=True,
            )
        )
        return
    release = (
        runtime.control_metadata.dataset_release(arguments.release_id)
        if arguments.release_id
        else runtime.control_metadata.latest_dataset_release()
    )
    if release is None:
        raise RuntimeError("capacity Dataset Release is unavailable")
    print(
        json.dumps(
            run_worker(runtime, release),
            ensure_ascii=False,
            sort_keys=True,
        )
    )


async def run_scenario(
    *,
    temporal_address: str,
    namespace: str,
) -> dict[str, object]:
    client = await Client.connect(temporal_address, namespace=namespace)
    probe_id = f"capacity-{uuid4().hex}"
    prepare_id = f"{probe_id}/prepare"
    prepare_handle = await client.start_workflow(
        "CapacityQualificationDataWorkflow",
        {
            "operation": "prepare",
            "idempotency_key": "capacity-qualification-top3000-v1",
        },
        id=prepare_id,
        task_queue=DATASET_PUBLICATION_TASK_QUEUE,
        result_type=dict,
    )
    prepare = await _resilient_workflow_result(
        prepare_handle,
        workflow_id=prepare_id,
        temporal_address=temporal_address,
        namespace=namespace,
    )
    release_id = str(prepare["release_id"])
    compute_ids = [f"{probe_id}/compute/{index}" for index in range(4)]
    compute_handles = [
        await client.start_workflow(
            "CapacityQualificationComputeWorkflow",
            {"release_id": release_id, "ordinal": str(index)},
            id=workflow_id,
            task_queue=COMPUTE_WORKFLOW_TASK_QUEUE,
            result_type=dict,
        )
        for index, workflow_id in enumerate(compute_ids)
    ]
    publication_id = f"{probe_id}/increment"
    publication_handle = await client.start_workflow(
        "CapacityQualificationDataWorkflow",
        {
            "operation": "increment",
            "idempotency_key": f"{probe_id}-increment",
        },
        id=publication_id,
        task_queue=DATASET_PUBLICATION_TASK_QUEUE,
        result_type=dict,
    )
    started = time.monotonic()
    compute_workers, publication = await asyncio.gather(
        asyncio.gather(
            *(
                _resilient_workflow_result(
                    handle,
                    workflow_id=workflow_id,
                    temporal_address=temporal_address,
                    namespace=namespace,
                )
                for handle, workflow_id in zip(
                    compute_handles,
                    compute_ids,
                    strict=True,
                )
            )
        ),
        _resilient_workflow_result(
            publication_handle,
            workflow_id=publication_id,
            temporal_address=temporal_address,
            namespace=namespace,
        ),
    )
    return {
        "probe_id": probe_id,
        "prepare": prepare,
        "compute_workers": compute_workers,
        "dataset_publication": publication,
        "wall_seconds": time.monotonic() - started,
    }


async def _resilient_workflow_result(
    handle: WorkflowResultHandle,
    *,
    workflow_id: str,
    temporal_address: str,
    namespace: str,
) -> dict[str, object]:
    while True:
        try:
            return await handle.result()
        except RPCError:
            await asyncio.sleep(RESULT_RETRY_SECONDS)
            try:
                client = await Client.connect(
                    temporal_address,
                    namespace=namespace,
                )
            except (RPCError, RuntimeError):
                continue
            handle = client.get_workflow_handle(workflow_id, result_type=dict)


def run_worker(
    runtime: RuntimePorts,
    release: dict[str, object],
) -> dict[str, object]:
    sampler = MemorySampler()
    sampler.start()
    started = time.monotonic()
    definition = maximum_definition()
    window = load_columnar_research_window(
        runtime.objects,
        release,
        definition,
    )
    loaded = time.monotonic()
    artifacts = calculate_bounded_research(window, definition)
    calculated = time.monotonic()
    result_entries = publish_compact_result_objects(
        runtime.objects,
        artifacts,
        definition,
    )
    cache_verified = _verify_working_cache(runtime, release)
    finished = time.monotonic()
    measurement = sampler.stop()
    return {
        "status": "succeeded",
        "release_id": release["id"],
        "universe": "top3000",
        "load_seconds": loaded - started,
        "calculate_seconds": calculated - loaded,
        "publish_seconds": finished - calculated,
        "wall_seconds": finished - started,
        **measurement,
        "result_bytes": sum(int(value["bytes"]) for value in result_entries.values()),
        "result_kinds": sorted(result_entries),
        "alpha_checksum": artifacts["alpha_matrix"]["checksum"],
        "strategy_checksum": artifacts["strategy_backtest"]["checksum"],
        "working_cache_verified": cache_verified,
    }


class MemorySampler:
    def __init__(self) -> None:
        self.samples: list[float] = []
        self.swap_samples: list[int] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._memory_path = Path("/sys/fs/cgroup/memory.current")
        self._swap_path = Path("/sys/fs/cgroup/memory.swap.current")

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> dict[str, object]:
        self._stop.set()
        self._thread.join(timeout=2)
        if not self.samples:
            self.samples.append(_process_peak_memory_mib())
        ordered = sorted(self.samples)
        p99_index = max(0, math.ceil(len(ordered) * 0.99) - 1)
        return {
            "p99_memory_mib": ordered[p99_index],
            "peak_memory_mib": max(ordered),
            "memory_sample_count": len(ordered),
            "swap_used": any(value > 0 for value in self.swap_samples),
        }

    def _sample(self) -> None:
        while not self._stop.wait(0.25):
            if self._memory_path.is_file():
                self.samples.append(
                    int(self._memory_path.read_text().strip()) / 1024 / 1024
                )
                if self._swap_path.is_file():
                    self.swap_samples.append(
                        int(self._swap_path.read_text().strip())
                    )
            else:
                self.samples.append(_process_peak_memory_mib())


def _process_peak_memory_mib() -> float:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform == "darwin":
        return value / 1024 / 1024
    return value / 1024


def _verify_working_cache(
    runtime: RuntimePorts,
    release: dict[str, object],
) -> bool:
    track_id = f"capacity-{uuid4().hex}"
    coordinates = {
        "daily_track_id": track_id,
        "generation_id": "capacity-generation",
        "basis_checkpoint_id": "capacity-checkpoint",
        "basis_checkpoint_sha256": "1" * 64,
        "definition_content_hash": "2" * 64,
        "calculation_kernel": "kernel-v1",
        "numeric_execution_contract": "thesistrace-numeric-v1",
        "basis_dataset_release_id": str(release["id"]),
        "fencing_token": 1,
    }
    runtime.working_cache.commit_seed(
        coordinates,
        pending_alpha={},
        rolling_factor=[
            {
                "session": "capacity",
                "horizon": 1,
                "sample_count": 3000,
                "ic": 0.0,
                "rank_ic": 0.0,
                "q1": 0.0,
                "q2": 0.0,
                "q3": 0.0,
                "q4": 0.0,
                "q5": 0.0,
                "top_bottom_return": 0.0,
                "correlation_reason": None,
                "quantile_reason": None,
            }
        ],
    )
    try:
        runtime.working_cache.validate(track_id, coordinates)
        return True
    finally:
        runtime.working_cache.delete(track_id)


def _runtime(local_root: Path | None) -> RuntimePorts:
    if local_root is None:
        return build_runtime(settings_from_environment())
    metadata = MetadataStore(local_root / "metadata.sqlite3")
    metadata.initialize()
    return RuntimePorts(
        control_metadata=metadata,
        objects=ImmutableObjectStore(local_root / "objects"),
        working_cache=WorkingCacheStore(local_root / "working-cache"),
        execution_dispatch=LocalWorkerDispatch(),
    )


if __name__ == "__main__":
    main()
