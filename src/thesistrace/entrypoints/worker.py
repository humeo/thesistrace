from __future__ import annotations

import argparse
import logging
import time

from thesistrace.daily_track import DailyTrackProgressionFailed
from thesistrace.entrypoints.runtime import CoreRuntime, CoreSettings, open_core_runtime

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the canonical ThesisTrace Core worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--healthcheck", action="store_true")
    arguments = parser.parse_args()
    settings = CoreSettings.from_environment()

    with open_core_runtime(settings) as runtime:
        if arguments.healthcheck:
            return
        _process_once(runtime)
        if arguments.once:
            return
        while True:
            time.sleep(5)
            _process_once(runtime)


def _process_once(runtime: CoreRuntime) -> None:
    if runtime.research_runs.process_next():
        logger.info("Core worker processed ResearchRun")
    removed_caches = runtime.daily_tracks.reconcile_stopped_working_cache()
    if removed_caches:
        logger.info(
            "Core worker removed stopped DailyTrack Working Cache entries",
            extra={"removed_cache_count": removed_caches},
        )
    while True:
        try:
            while runtime.daily_tracks.process_next():
                logger.info("Core worker advanced DailyTrack")
            return
        except DailyTrackProgressionFailed as error:
            logger.error(
                "Core worker isolated one DailyTrack failure at its current target",
                extra={"error_type": type(error.__cause__).__name__},
            )
if __name__ == "__main__":
    main()
