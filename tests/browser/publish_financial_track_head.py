from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

from prepare_current_data import CURRENT_SESSIONS, _canonical, _financial_candidate

from thesistrace._postgres import PostgresDatabase
from thesistrace.data import DatasetLifecycle, MountedGenerationStore
from thesistrace.entrypoints.runtime import CoreSettings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("lagged", "recovered"))
    mode = parser.parse_args().mode
    settings = CoreSettings.from_environment()
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        lifecycle = DatasetLifecycle(database, settings.data_mount)
        current = lifecycle.current_pointer()
        if current is None:
            raise RuntimeError("Browser fixture Head is unavailable")
        store = MountedGenerationStore(settings.data_mount)
        market = store.materialize(
            _canonical(CURRENT_SESSIONS),
            prepared_at=datetime(2026, 8, 11, 14, tzinfo=UTC),
            source_name="ticket-11-browser-track-fixture",
            source_lineage={"contract": "financial-track-browser-v1", "mode": mode},
        )
        observation_through = "2026-08-06" if mode == "lagged" else CURRENT_SESSIONS[-1]
        operation_id = f"ticket-11-browser-{mode}"
        financial = _financial_candidate(
            settings,
            market.manifest_sha256,
            observation_through_session=observation_through,
            idempotency_key=operation_id,
        )
        generation = store.compose_financial_candidate(
            market.manifest_sha256,
            financial.manifest_sha256,
            prepared_at=datetime(2026, 8, 11, 15, tzinfo=UTC),
        )
        lifecycle.protect_candidate(
            operation_id=operation_id,
            generation_manifest_sha256=generation.manifest_sha256,
            lease_seconds=60,
        )
        lifecycle.compare_and_swap_head(
            expected_generation_manifest_sha256=current.generation_manifest_sha256,
            candidate_generation_manifest_sha256=generation.manifest_sha256,
            operation_id=operation_id,
        )
    finally:
        database.close()
    print(
        json.dumps(
            {
                "generation_manifest_sha256": generation.manifest_sha256,
                "mode": mode,
                "observation_through_session": observation_through,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
