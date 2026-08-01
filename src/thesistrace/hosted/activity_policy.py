from datetime import timedelta

from temporalio.common import RetryPolicy

from thesistrace.activity_contract import (
    MAX_AUTOMATIC_ACTIVITY_EXECUTIONS,
    MAX_RESOURCE_EXHAUSTION_EXECUTIONS,
)

HEAVY_ACTIVITY_HEARTBEAT_TIMEOUT = timedelta(minutes=5)


def heavy_activity_retry_policy() -> RetryPolicy:
    return RetryPolicy(
        initial_interval=timedelta(seconds=1),
        backoff_coefficient=2,
        maximum_interval=timedelta(seconds=30),
        maximum_attempts=MAX_AUTOMATIC_ACTIVITY_EXECUTIONS,
    )


def resource_aware_activity_retry_policy() -> RetryPolicy:
    return RetryPolicy(
        initial_interval=timedelta(seconds=1),
        backoff_coefficient=2,
        maximum_interval=timedelta(seconds=30),
        maximum_attempts=MAX_RESOURCE_EXHAUSTION_EXECUTIONS,
    )
