from __future__ import annotations

import argparse
import sys

from thesistrace.alpha_language import alpha_language
from thesistrace.data import DatasetAdmissionService, DatasetLifecycle, MountedGenerationStore
from thesistrace.entrypoints.runtime import CoreSettings, open_core_runtime
from thesistrace.research_run import ResearchRunService
from thesistrace.research_run.execution import SupervisedResearchExecutor


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    arguments = parser.parse_args()
    settings = CoreSettings.from_environment()

    def progress(stage: str, run_id: str) -> None:
        if stage != "claimed" or run_id != arguments.run_id:
            return
        print(f"claimed:{run_id}", flush=True)
        if sys.stdin.buffer.read(1) != b"1":
            raise RuntimeError("Browser ResearchRun barrier was not released")

    with open_core_runtime(settings) as runtime:
        service = ResearchRunService(
            runtime.database,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            publication=runtime.publication,
            execution=SupervisedResearchExecutor(settings.data_mount),
            progress=progress,
            activate_track=runtime.daily_tracks.activate,
            compile_formula=alpha_language.compile,
            current_dataset=DatasetAdmissionService(
                runtime.database,
                settings.data_mount,
            ).current,
            track_references_result=runtime.daily_tracks.references_result_manifest,
        )
        if not service.process_next():
            raise RuntimeError("Browser ResearchRun was not claimed")


if __name__ == "__main__":
    main()
