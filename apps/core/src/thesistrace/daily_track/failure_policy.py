from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TrackingAttemptFailurePolicy:
    code: str
    max_cycle_attempts: int


MAX_TRACKING_CYCLE_ATTEMPTS = 3

TRACKING_ATTEMPT_FAILURE_POLICIES = {
    "InfrastructureFailure": TrackingAttemptFailurePolicy(
        code="INFRASTRUCTURE_FAILURE",
        max_cycle_attempts=MAX_TRACKING_CYCLE_ATTEMPTS,
    ),
    "WorkerLost": TrackingAttemptFailurePolicy(
        code="WORKER_LOST",
        max_cycle_attempts=MAX_TRACKING_CYCLE_ATTEMPTS,
    ),
    "FinancialCoverageUnavailable": TrackingAttemptFailurePolicy(
        code="FINANCIAL_COVERAGE_UNAVAILABLE",
        max_cycle_attempts=1,
    ),
    "PublicationPreparationError": TrackingAttemptFailurePolicy(
        code="PUBLICATION_PREPARATION_ERROR",
        max_cycle_attempts=1,
    ),
    "TrackingExecutionError": TrackingAttemptFailurePolicy(
        code="TRACKING_EXECUTION_ERROR",
        max_cycle_attempts=1,
    ),
    "NumericContractError": TrackingAttemptFailurePolicy(
        code="NUMERIC_CONTRACT_ERROR",
        max_cycle_attempts=1,
    ),
    "UserStopped": TrackingAttemptFailurePolicy(
        code="USER_STOPPED",
        max_cycle_attempts=1,
    ),
}

def tracking_attempt_failure_code(reason: object) -> str | None:
    if reason is None:
        return None
    if not isinstance(reason, str):
        return "UNCLASSIFIED_FAILURE"
    policy = TRACKING_ATTEMPT_FAILURE_POLICIES.get(reason)
    return "UNCLASSIFIED_FAILURE" if policy is None else policy.code


def tracking_attempt_retry_eligible(reason: object, cycle_attempt_ordinal: int) -> bool:
    if not isinstance(reason, str):
        return False
    policy = TRACKING_ATTEMPT_FAILURE_POLICIES.get(reason)
    return (
        policy is not None
        and cycle_attempt_ordinal < policy.max_cycle_attempts
    )


__all__ = (
    "MAX_TRACKING_CYCLE_ATTEMPTS",
    "TRACKING_ATTEMPT_FAILURE_POLICIES",
    "TrackingAttemptFailurePolicy",
    "tracking_attempt_failure_code",
    "tracking_attempt_retry_eligible",
)
