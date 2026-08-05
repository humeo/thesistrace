import argparse
import logging
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from thesistrace.config import settings_from_environment
from thesistrace.runtime import build_runtime

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
    while True:
        store.record_worker_heartbeat(datetime.now(UTC))
        if args.role == "data":
            if args.once:
                return
            time.sleep(args.interval)
            continue
        store.record_worker_heartbeat(datetime.now(UTC))
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
