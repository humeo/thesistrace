import argparse
import logging
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from thesistrace.config import settings_from_environment
from thesistrace.datasets import DatasetPublisher
from thesistrace.research_runs import ResearchRunService
from thesistrace.runtime import build_runtime
from thesistrace.tracking import DailyTrackingService

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the ThesisTrace worker")
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--objects", type=Path)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument(
        "--role",
        choices=("local", "compute", "data"),
        default="local",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = settings_from_environment()
    settings = replace(
        settings,
        metadata_path=args.metadata or settings.metadata_path,
        object_root=args.objects or settings.object_root,
    )
    runtime = build_runtime(settings)
    store = runtime.control_metadata
    objects = runtime.objects
    runs = ResearchRunService(
        store,
        DatasetPublisher(store, objects),
        objects,
    )
    tracking = DailyTrackingService(
        store,
        DatasetPublisher(store, objects),
        objects,
        runtime.working_cache,
    )
    while True:
        store.record_worker_heartbeat(datetime.now(UTC))
        if args.role == "data":
            if args.once:
                return
            time.sleep(args.interval)
            continue
        try:
            tracking.reconcile_activation_staging()
            tracking.reconcile_cache_deletions()
            store.recover_abandoned_research_runs(
                stale_after_seconds=settings.worker_stale_after_seconds
            )
            tracking.recover_abandoned_attempts(
                stale_after_seconds=settings.worker_stale_after_seconds
            )
            latest_release = store.latest_dataset_release()
            if latest_release is not None:
                enqueue_failures = tracking.enqueue_active_tracks(str(latest_release["id"]))
                for failure in enqueue_failures:
                    logger.warning(
                        "%s for %s: %s",
                        failure["reason_code"],
                        failure["track_id"],
                        failure["message"],
                    )
            runs.execute_next()
            tracking.execute_next()
        except Exception:
            logger.exception("ResearchRun worker iteration failed")
        store.record_worker_heartbeat(datetime.now(UTC))
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
