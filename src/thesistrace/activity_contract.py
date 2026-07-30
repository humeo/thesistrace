import errno

MAX_AUTOMATIC_ACTIVITY_EXECUTIONS = 3
MAX_RESOURCE_EXHAUSTION_EXECUTIONS = 2


class CooperativeActivityCancellation(RuntimeError):
    pass


def is_resource_exhaustion(error: BaseException) -> bool:
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, MemoryError):
            return True
        if isinstance(current, OSError) and current.errno in {
            errno.ENOMEM,
            errno.ENOSPC,
        }:
            return True
        current = current.__cause__ or current.__context__
    return False


def should_retry_resource_exhaustion(execution_ordinal: int) -> bool:
    return execution_ordinal < MAX_RESOURCE_EXHAUSTION_EXECUTIONS
