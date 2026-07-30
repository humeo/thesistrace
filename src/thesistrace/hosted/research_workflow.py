from datetime import timedelta

from temporalio import workflow

RESEARCH_TASK_QUEUE = "thesistrace-compute"


@workflow.defn
class ResearchWorkflow:
    @workflow.run
    async def run(self, request: dict[str, str]) -> dict[str, str]:
        return await workflow.execute_activity(
            "execute_research_run",
            request,
            result_type=dict,
            start_to_close_timeout=timedelta(hours=2),
        )


def research_workflow_id(run_id: str) -> str:
    return f"research-run/{run_id}"
