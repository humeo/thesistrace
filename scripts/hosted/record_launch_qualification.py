import argparse
import json
import os
from pathlib import Path

from thesistrace.config import settings_from_environment
from thesistrace.launch import LaunchQualificationService
from thesistrace.management import build_management_store
from thesistrace.storage import MetadataStore


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Record evidence produced by the complete release acceptance runner",
    )
    result.add_argument("--actor", required=True)
    result.add_argument("--release-bundle-id", required=True)
    result.add_argument("--evidence", type=Path, required=True)
    result.add_argument("--attestation", required=True)
    result.add_argument("--attestation-key-file", type=Path, required=True)
    return result


def main() -> None:
    if os.environ.get("THESISTRACE_ACCEPTANCE_MODE") != "1":
        raise SystemExit("launch qualification recording is acceptance-only")
    arguments = parser().parse_args()
    evidence = json.loads(arguments.evidence.read_text(encoding="utf-8"))
    if not isinstance(evidence, dict):
        raise SystemExit("launch evidence must be a JSON object")
    settings = settings_from_environment()
    local_store = MetadataStore(settings.metadata_path)
    if not settings.database_url:
        local_store.initialize()
    store = build_management_store(settings, local_store)
    attestation_key = arguments.attestation_key_file.read_bytes()
    qualification = LaunchQualificationService(store).record(
        actor=arguments.actor,
        release_bundle_id=arguments.release_bundle_id,
        evidence=evidence,
        attestation=arguments.attestation,
        attestation_key=attestation_key,
    )
    print(json.dumps(qualification, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
