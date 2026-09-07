from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AttemptFailurePolicy:
    code: str
    max_attempts: int


MAX_RESEARCH_RUN_ATTEMPTS = 3

ATTEMPT_FAILURE_POLICIES = {
    "InsufficientCalculationWarmup": AttemptFailurePolicy(
        code="INSUFFICIENT_CALCULATION_WARMUP",
        max_attempts=1,
    ),
    "SelectedDataInvalid": AttemptFailurePolicy(
        code="SELECTED_DATA_INVALID",
        max_attempts=1,
    ),
    "ResourceExhausted": AttemptFailurePolicy(
        code="RESOURCE_EXHAUSTED",
        max_attempts=1,
    ),
    "InfrastructureUnavailable": AttemptFailurePolicy(
        code="INFRASTRUCTURE_UNAVAILABLE",
        max_attempts=MAX_RESEARCH_RUN_ATTEMPTS,
    ),
    "CheckpointIntegrityFailure": AttemptFailurePolicy(
        code="CHECKPOINT_INTEGRITY_FAILURE",
        max_attempts=1,
    ),
    "ContractMismatch": AttemptFailurePolicy(
        code="CONTRACT_MISMATCH",
        max_attempts=1,
    ),
    "CalculationFailure": AttemptFailurePolicy(
        code="CALCULATION_FAILURE",
        max_attempts=1,
    ),
    "PermanentExecutionFailure": AttemptFailurePolicy(
        code="PERMANENT_EXECUTION_FAILURE",
        max_attempts=1,
    ),
    "WorkerLost": AttemptFailurePolicy(
        code="WORKER_LOST",
        max_attempts=MAX_RESEARCH_RUN_ATTEMPTS,
    ),
    "UserCancelled": AttemptFailurePolicy(
        code="USER_CANCELLED",
        max_attempts=1,
    ),
}

RETRYABLE_ATTEMPT_FAILURES = tuple(
    reason
    for reason, policy in ATTEMPT_FAILURE_POLICIES.items()
    if policy.max_attempts > 1
)


def attempt_failure_code(reason: object) -> str | None:
    if reason is None:
        return None
    if not isinstance(reason, str):
        return "UNCLASSIFIED_FAILURE"
    policy = ATTEMPT_FAILURE_POLICIES.get(reason)
    return "UNCLASSIFIED_FAILURE" if policy is None else policy.code


def attempt_retry_eligible(reason: object, attempt_ordinal: int) -> bool:
    if not isinstance(reason, str):
        return False
    policy = ATTEMPT_FAILURE_POLICIES.get(reason)
    return policy is not None and attempt_ordinal < policy.max_attempts


__all__ = (
    "ATTEMPT_FAILURE_POLICIES",
    "MAX_RESEARCH_RUN_ATTEMPTS",
    "RETRYABLE_ATTEMPT_FAILURES",
    "AttemptFailurePolicy",
    "attempt_failure_code",
    "attempt_retry_eligible",
)
