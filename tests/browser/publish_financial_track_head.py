from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from thesistrace._postgres import PostgresDatabase
from thesistrace.data import DatasetLifecycle, MountedGenerationStore
from thesistrace.entrypoints.runtime import CoreSettings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("lagged", "recovered"))
    mode = parser.parse_args().mode
    settings = CoreSettings.from_environment()
    fixture_root = Path(__file__).resolve().parents[1] / "fixtures"
    if mode == "lagged":
        _run_operator(
            "refresh",
            "--idempotency-key",
            "financial-release-market-refresh",
            "--as-of",
            "2026-08-11T18:00:00+08:00",
        )
        outcome = _run_operator(
            "work-refresh",
            "--replay",
            str(fixture_root / "tushare-financial-market-refresh-replay.json"),
        )
    else:
        database = PostgresDatabase(settings.database_url)
        database.open()
        try:
            pointer = DatasetLifecycle(database, settings.data_mount).current_pointer()
            if pointer is None:
                raise RuntimeError("financial release Head is unavailable")
            root = MountedGenerationStore(settings.data_mount).inspect_root(
                pointer.generation_manifest_sha256
            )
        finally:
            database.close()
        prior = root.financial_candidate_manifest_sha256
        if prior is None:
            raise RuntimeError("financial release candidate is unavailable")
        outcome = _run_operator(
            "refresh-financial",
            "--idempotency-key",
            "financial-release-financial-refresh",
            "--generation-manifest-sha256",
            root.manifest_sha256,
            "--capability-report",
            str(fixture_root / "tushare-financial-capability.json"),
            "--prior-candidate-manifest-sha256",
            prior,
            "--observation-through-session",
            "2026-08-11",
            "--replay",
            str(fixture_root / "tushare-financial-product-replay.json"),
        )
    print(json.dumps({"mode": mode, "operator_outcome": outcome}, sort_keys=True))


def _run_operator(*arguments: str) -> dict[str, object]:
    completed = subprocess.run(
        ["thesistrace-data-operator", *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"private Data Operator failed ({completed.returncode}): {completed.stderr}"
        )
    outcome = json.loads(completed.stdout)
    if not isinstance(outcome, dict):
        raise RuntimeError("private Data Operator returned an invalid outcome")
    return outcome


if __name__ == "__main__":
    main()
