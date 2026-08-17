from __future__ import annotations

import json
import sys

from thesistrace.entrypoints.runtime import CoreSettings, open_core_runtime
from thesistrace.entrypoints.worker import (
    DEVELOPMENT_CALCULATION_THREADS,
    DEVELOPMENT_CPU_COUNT,
    DEVELOPMENT_EXECUTION_MEMORY_BYTES,
    DEVELOPMENT_MEMORY_BYTES,
    WorkerCapacity,
    WorkerConfiguration,
    WorkerRole,
    process_one_poll,
)


def main() -> None:
    role = WorkerRole(sys.argv[1])
    configuration = WorkerConfiguration(
        role=role,
        capacity=WorkerCapacity(
            cpu_count=DEVELOPMENT_CPU_COUNT,
            memory_bytes=DEVELOPMENT_MEMORY_BYTES,
            execution_memory_bytes=DEVELOPMENT_EXECUTION_MEMORY_BYTES,
            calculation_threads=DEVELOPMENT_CALCULATION_THREADS,
        ),
    )

    def emit(event: dict[str, object]) -> None:
        print(json.dumps(event, sort_keys=True), flush=True)
        if event.get("event") == "worker_claim":
            if not sys.stdin.readline():
                raise RuntimeError("claim barrier closed before release")

    with open_core_runtime(CoreSettings.from_environment()) as runtime:
        process_one_poll(runtime, configuration, emit=emit)


if __name__ == "__main__":
    main()
