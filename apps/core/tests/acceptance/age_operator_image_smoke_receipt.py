from __future__ import annotations

import json
import sys

from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.runtime import CoreSettings


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: age_operator_image_smoke_receipt.py IDEMPOTENCY_KEY")
    key = sys.argv[1]
    settings = CoreSettings.from_environment()
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                UPDATE data.refresh_operations
                SET created_at = clock_timestamp() - interval '182 days',
                    started_at = CASE
                        WHEN started_at IS NULL THEN NULL
                        ELSE clock_timestamp() - interval '181 days 1 hour'
                    END,
                    last_heartbeat_at = CASE
                        WHEN last_heartbeat_at IS NULL THEN NULL
                        ELSE clock_timestamp() - interval '181 days 1 hour'
                    END,
                    last_refresh_at = CASE
                        WHEN last_refresh_at IS NULL THEN NULL
                        ELSE clock_timestamp() - interval '181 days'
                    END,
                    finished_at = clock_timestamp() - interval '181 days',
                    updated_at = clock_timestamp() - interval '181 days'
                WHERE idempotency_key = %s
                  AND status IN ('succeeded', 'failed', 'cancelled')
                RETURNING kind, status
                """,
                (key,),
            ).fetchone()
        if row is None:
            raise AssertionError("Production Image terminal receipt was not found")
        print(
            json.dumps(
                {
                    "idempotency_key": key,
                    "kind": str(row["kind"]),
                    "status": str(row["status"]),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    finally:
        database.close()


if __name__ == "__main__":
    main()
