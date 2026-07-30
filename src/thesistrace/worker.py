import argparse
import time
from datetime import UTC, datetime
from pathlib import Path

from thesistrace.storage import MetadataStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the ThesisTrace worker")
    parser.add_argument("--metadata", type=Path, default=Path(".local/metadata.sqlite3"))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=5.0)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    store = MetadataStore(args.metadata)
    store.initialize()
    while True:
        store.record_worker_heartbeat(datetime.now(UTC))
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
