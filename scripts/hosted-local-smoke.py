#!/usr/bin/env python3
import importlib.util
import json
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
RELEASE_SMOKE = ROOT / "scripts" / "hosted-release-smoke.py"


class LocalPublicOriginFailure(RuntimeError):
    pass


def release_smoke_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "thesistrace_hosted_release_smoke",
        RELEASE_SMOKE,
    )
    if spec is None or spec.loader is None:
        raise LocalPublicOriginFailure("Hosted public-origin smoke could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_local_evidence(evidence: dict[str, object]) -> None:
    required_interruptions = {
        "activity",
        "api",
        "no_duplicate_domain_result",
        "no_partial_authoritative_artifact",
        "outbox_relay",
        "publication",
        "temporal_worker",
    }
    interruptions = evidence.get("interruption_matrix")
    if (
        evidence.get("status") != "passed"
        or evidence.get("schema_version") != "hosted-local-public-origin-v1"
        or evidence.get("profile") != "local"
        or evidence.get("bounded_result") is not True
        or evidence.get("bounded_time_series") is not True
        or evidence.get("deleted_resources_inaccessible") is not True
        or evidence.get("three_health_planes") is not False
        or not isinstance(interruptions, dict)
        or any(interruptions.get(name) is not True for name in required_interruptions)
        or "maintenance" in interruptions
        or "node" in interruptions
    ):
        raise LocalPublicOriginFailure(
            f"Hosted Local public-origin evidence is incomplete: {evidence}"
        )


def main() -> None:
    release_smoke = release_smoke_module()
    evidence = release_smoke.run_public_origin_acceptance("local")
    validate_local_evidence(evidence)
    print(json.dumps(evidence, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except LocalPublicOriginFailure as error:
        raise SystemExit(str(error)) from error
