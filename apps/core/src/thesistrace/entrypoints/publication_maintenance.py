from __future__ import annotations

import argparse
import os
import signal
import time
from pathlib import Path
from threading import Event

HEARTBEAT = Path("/tmp/thesistrace-publication-maintenance.heartbeat")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run bounded Publication maintenance")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--health", action="store_true")
    arguments = parser.parse_args()
    if arguments.health:
        try:
            age = time.monotonic() - float(HEARTBEAT.read_text())
            raise SystemExit(0 if 0 <= age < 60 else 1)
        except (OSError, ValueError):
            raise SystemExit(1) from None
    import boto3

    from thesistrace._postgres import PostgresDatabase
    from thesistrace.entrypoints.schema import verify_core_schema
    from thesistrace.operational_events import emit_operational_event_data
    from thesistrace.publication import PublicationMaintenance, publication_request_config

    stopped = Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    if not arguments.once:
        HEARTBEAT.unlink(missing_ok=True)
    database = PostgresDatabase(os.environ["THESISTRACE_DATABASE_URL"], pool_max_size=1)
    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ["THESISTRACE_S3_ENDPOINT_URL"],
        aws_access_key_id=os.environ["THESISTRACE_S3_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["THESISTRACE_S3_SECRET_ACCESS_KEY"],
        region_name=os.environ.get("THESISTRACE_S3_REGION", "us-east-1"),
        config=publication_request_config(),
    )
    try:
        database.open()
        verify_core_schema(database)
        maintenance = PublicationMaintenance(
            database, s3, bucket=os.environ["THESISTRACE_S3_BUCKET"]
        )
        while not stopped.is_set():
            result = maintenance.run_once()
            event = {
                "component": "publication_maintenance",
                "event": "publication_maintenance_step",
                "status": result["status"],
                "phase": result.get("job"),
                "duration_ms": int(float(result.get("elapsed_seconds", 0)) * 1000),
                "failure_code": result.get("failure_code"),
                "retry_seconds": result.get("retry_seconds"),
            }
            for count in ("listed", "processed", "deleted", "skipped"):
                event[f"{count}_count"] = result.get(count)
            for name in (
                "full_sweep_age_seconds",
                "oldest_deletion_age_seconds",
                "sweep_completed",
            ):
                event[name] = result.get(name)
            emit_operational_event_data(event)
            if arguments.once:
                break
            HEARTBEAT.write_text(str(time.monotonic()))
            stopped.wait(5)
    except Exception:
        emit_operational_event_data(
            {
                "component": "publication_maintenance",
                "event": "publication_maintenance_failed",
                "failure_code": "PUBLICATION_MAINTENANCE_UNAVAILABLE",
            }
        )
        raise SystemExit(1) from None
    finally:
        s3.close()
        database.close()
        if not arguments.once:
            HEARTBEAT.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
