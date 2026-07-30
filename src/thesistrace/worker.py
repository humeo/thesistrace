import argparse
import time
from datetime import UTC, datetime
from pathlib import Path

from thesistrace.config import settings_from_environment
from thesistrace.storage import MetadataStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the ThesisTrace worker")
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=5.0)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    metadata_path = args.metadata or settings_from_environment().metadata_path
    store = MetadataStore(metadata_path)
    store.initialize()
    while True:
        store.record_worker_heartbeat(datetime.now(UTC))
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
