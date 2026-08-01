#!/usr/bin/env python3
import argparse
import json
import subprocess
from pathlib import Path

STEADY_SERVICES = (
    "postgres",
    "temporal-postgres",
    "temporal",
    "postgrest",
    "deno",
    "insforge",
    "object-store",
    "api",
    "execution-relay",
    "tushare-egress",
    "health-service",
    "otel-collector",
    "prometheus",
    "grafana",
    "edge",
)
COMPUTE_SERVICES = tuple(f"compute-worker-{index}" for index in range(1, 5))
DATA_SERVICE = "data-worker"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--namespace", default="thesistrace")
    parser.add_argument("--compose-file", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--release-bundle-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def run(arguments: argparse.Namespace) -> dict[str, object]:
    before = container_state(arguments)
    coordinator_id = _container_id(arguments.project, DATA_SERVICE)
    scenario = json.loads(
        subprocess.check_output(
            [
                "docker",
                "exec",
                coordinator_id,
                "python",
                "-m",
                "thesistrace.hosted.capacity_probe",
                "scenario",
                "--temporal-address",
                "temporal:7233",
                "--namespace",
                arguments.namespace,
            ],
            text=True,
        )
    )
    prepare = scenario["prepare"]
    compute_workers = scenario["compute_workers"]
    publication = scenario["dataset_publication"]
    after = container_state(arguments)
    worker_slots = {str(value["worker_slot"]) for value in compute_workers}
    checksums = {
        (str(value["alpha_checksum"]), str(value["strategy_checksum"]))
        for value in compute_workers
    }
    nonworker_memory = sum(
        int(after[name]["memory_limit_bytes"]) for name in STEADY_SERVICES
    )
    nonworker_cpu = sum(
        float(after[name]["cpu_limit"]) for name in STEADY_SERVICES
    )
    unexpected_restart = any(
        int(after[name]["restart_count"]) != int(before[name]["restart_count"])
        for name in (*STEADY_SERVICES, *COMPUTE_SERVICES, DATA_SERVICE)
    )
    oom_kill = any(
        bool(after[name]["oom_killed"])
        for name in (*STEADY_SERVICES, *COMPUTE_SERVICES, DATA_SERVICE)
    )
    missing_heartbeat = any(
        after[name]["health"] != "healthy"
        for name in (*COMPUTE_SERVICES, DATA_SERVICE)
    )
    return {
        "schema_version": "capacity-qualification-v1",
        "probe_id": scenario["probe_id"],
        "release_bundle_id": arguments.release_bundle_id,
        "universe": "top3000",
        "wall_seconds": scenario["wall_seconds"],
        "compute_workers": compute_workers,
        "dataset_publication": publication,
        "nonworker_services": {
            "memory_limit_mib": nonworker_memory / 1024 / 1024,
            "cpu_limit": nonworker_cpu,
        },
        "swap_used": any(bool(value["swap_used"]) for value in compute_workers)
        or any(
            after[name]["swap_disabled"] is not True
            for name in (*STEADY_SERVICES, *COMPUTE_SERVICES, DATA_SERVICE)
        ),
        "oom_kill": oom_kill,
        "unexpected_restart": unexpected_restart,
        "missing_heartbeat": missing_heartbeat,
        "duplicate_publication": publication.get("created") is not True
        or publication.get("activity_attempt") != 1,
        "incorrect_result": len(checksums) != 1
        or len(worker_slots) != 4
        or any(value.get("status") != "succeeded" for value in compute_workers)
        or any(value.get("activity_attempt") != 1 for value in compute_workers)
        or any(int(value.get("result_bytes", 0)) > 1_048_576 for value in compute_workers),
        "production_paths": {
            "parquet": True,
            "result_bundle": all(bool(value.get("result_kinds")) for value in compute_workers),
            "working_cache": all(
                value.get("working_cache_verified") is True
                for value in compute_workers
            ),
            "postgresql": prepare.get("created") is True,
            "temporal": all(bool(value.get("workflow_id")) for value in compute_workers)
            and bool(publication.get("workflow_id")),
            "object_store": all(int(value.get("result_bytes", 0)) > 0 for value in compute_workers),
        },
        "container_state_before": before,
        "container_state_after": after,
    }


def container_state(arguments: argparse.Namespace) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for service in (*STEADY_SERVICES, *COMPUTE_SERVICES, DATA_SERVICE):
        container_id = _container_id(arguments.project, service)
        value = json.loads(
            subprocess.check_output(
                ["docker", "inspect", container_id],
                text=True,
            )
        )[0]
        state = value["State"]
        host = value["HostConfig"]
        memory_limit = int(host.get("Memory", 0))
        memory_swap_limit = int(host.get("MemorySwap", 0))
        result[service] = {
            "container_id": container_id,
            "health": state.get("Health", {}).get("Status", "none"),
            "oom_killed": bool(state.get("OOMKilled")),
            "restart_count": int(value.get("RestartCount", 0)),
            "memory_limit_bytes": memory_limit,
            "memory_swap_limit_bytes": memory_swap_limit,
            "swap_disabled": memory_limit > 0 and memory_swap_limit == memory_limit,
            "cpu_limit": int(host.get("NanoCpus", 0)) / 1_000_000_000,
        }
    return result


def _container_id(project: str, service: str) -> str:
    container_ids = subprocess.check_output(
        [
            "docker",
            "ps",
            "-q",
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--filter",
            f"label=com.docker.compose.service={service}",
        ],
        text=True,
    ).splitlines()
    if len(container_ids) != 1:
        raise RuntimeError(
            f"expected one running Compose service {service}, found {len(container_ids)}"
        )
    return container_ids[0]


def main() -> None:
    arguments = build_parser().parse_args()
    evidence = run(arguments)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = arguments.output.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(arguments.output)
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
