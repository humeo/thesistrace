#!/usr/bin/env python3
import argparse
import importlib.util
import json
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
RELEASE_SMOKE = ROOT / "scripts" / "hosted-release-smoke.py"


class LocalPublicOriginFailure(RuntimeError):
    pass


GATE_METHODS = {
    "identity-product": "run_local_identity_product",
    "api-relay-recovery": "run_local_api_relay_recovery",
    "compute-recovery": "run_local_compute_recovery",
    "publication-recovery": "run_local_publication_recovery",
}


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


def validate_local_evidence(gate: str, evidence: dict[str, object]) -> None:
    if (
        evidence.get("status") != "passed"
        or evidence.get("schema_version") != "hosted-local-public-origin-gate-v1"
        or evidence.get("profile") != "local"
        or evidence.get("gate") != gate
    ):
        raise LocalPublicOriginFailure(
            f"Hosted Local {gate} evidence is incomplete: {evidence}"
        )


def run_gate(gate: str) -> dict[str, object]:
    release_smoke = release_smoke_module()
    try:
        method_name = GATE_METHODS[gate]
    except KeyError as error:
        raise LocalPublicOriginFailure(f"unknown Hosted Local gate: {gate}") from error
    method = getattr(release_smoke, method_name, None)
    if not callable(method):
        raise LocalPublicOriginFailure(f"Hosted public-origin smoke has no {gate} gate")
    evidence = method()
    if not isinstance(evidence, dict):
        raise LocalPublicOriginFailure(f"Hosted Local {gate} returned invalid evidence")
    return evidence


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Run one Hosted Local public-origin gate")
    result.add_argument("--gate", required=True, choices=tuple(GATE_METHODS))
    return result


def main() -> None:
    gate = parser().parse_args().gate
    evidence = run_gate(gate)
    validate_local_evidence(gate, evidence)
    print(json.dumps(evidence, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except LocalPublicOriginFailure as error:
        raise SystemExit(str(error)) from error
