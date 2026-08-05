from __future__ import annotations

import argparse
import logging
import time
from datetime import UTC, datetime, timedelta

from thesistrace.daily_track import DailyTrackProgressionFailed
from thesistrace.entrypoints.runtime import CoreRuntime, CoreSettings, open_core_runtime

logger = logging.getLogger(__name__)
ABANDONED_UPDATE_AFTER = timedelta(minutes=15)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the canonical ThesisTrace Core worker")
    parser.add_argument("--once", action="store_true")
    arguments = parser.parse_args()
    settings = CoreSettings.from_environment()

    with open_core_runtime(settings) as runtime:
        _process_once(runtime)
        if arguments.once:
            return
        while True:
            time.sleep(5)
            _process_once(runtime)


def _observe_data_state(status: str) -> None:
    logger.debug("Core worker observed Data state", extra={"data_status": status})


def _process_once(runtime: CoreRuntime) -> None:
    _process_data(runtime)
    if runtime.research_runs.process_next():
        logger.info("Core worker processed ResearchRun")
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


def _process_data(runtime: CoreRuntime) -> None:
    data = runtime.data
    recovered = data.recover_abandoned_updates(
        stale_before=datetime.now(UTC) - ABANDONED_UPDATE_AFTER
    )
    if recovered:
        logger.warning("Core worker recovered abandoned Data Update")
    processed = data.process_next_update()
    _observe_data_state(data.overview().status)
    if processed:
        logger.info("Core worker completed Data Update")


if __name__ == "__main__":
    main()
