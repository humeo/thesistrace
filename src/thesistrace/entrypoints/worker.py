from __future__ import annotations

import argparse
import logging
import time

from thesistrace.entrypoints.runtime import CoreRuntime, CoreSettings, open_core_runtime

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the canonical ThesisTrace Core worker")
    parser.add_argument("--once", action="store_true")
    arguments = parser.parse_args()
    settings = CoreSettings.from_environment()

    with open_core_runtime(settings) as runtime:
        _process_data(runtime)
        if arguments.once:
            return
        while True:
            time.sleep(5)
            _process_data(runtime)


def _observe_data_state(status: str) -> None:
    logger.debug("Core worker observed Data state", extra={"data_status": status})


def _process_data(runtime: CoreRuntime) -> None:
    data = runtime.data
    processed = data.process_next_update()
    _observe_data_state(data.overview().status)
    if processed:
        logger.info("Core worker completed Data Update")


if __name__ == "__main__":
    main()
