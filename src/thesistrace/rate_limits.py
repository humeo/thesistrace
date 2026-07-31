import math
import time
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class RateLimitRejection:
    dimension: str
    retry_after_seconds: int


@dataclass
class _Window:
    started_at: float
    count: int


class ApiRateLimiter:
    def __init__(
        self,
        *,
        window_seconds: int,
        user_request_limit: int,
        workspace_request_limit: int,
        mutation_request_limit: int,
    ) -> None:
        if min(
            window_seconds,
            user_request_limit,
            workspace_request_limit,
            mutation_request_limit,
        ) < 1:
            raise ValueError("API rate limits must be positive integers")
        self.window_seconds = window_seconds
        self.user_request_limit = user_request_limit
        self.workspace_request_limit = workspace_request_limit
        self.mutation_request_limit = mutation_request_limit
        self._windows: dict[tuple[str, str], _Window] = {}
        self._lock = Lock()

    def check(
        self,
        *,
        subject: str,
        workspace_id: str | None,
        state_changing: bool,
    ) -> RateLimitRejection | None:
        policies: list[tuple[str, str, int]] = []
        if state_changing:
            policies.append(
                (
                    "authenticated_state_changes",
                    subject,
                    self.mutation_request_limit,
                )
            )
            if workspace_id is not None:
                policies.append(
                    (
                        "personal_workspace_state_changes",
                        workspace_id,
                        self.mutation_request_limit,
                    )
                )
        policies.append(
            (
                "authenticated_user_requests",
                subject,
                self.user_request_limit,
            )
        )
        if workspace_id is not None:
            policies.append(
                (
                    "personal_workspace_requests",
                    workspace_id,
                    self.workspace_request_limit,
                )
            )

        now = time.monotonic()
        with self._lock:
            active = {
                key: window
                for key, window in self._windows.items()
                if now - window.started_at < self.window_seconds
            }
            self._windows = active
            for dimension, identity, limit in policies:
                window = active.get((dimension, identity))
                if window is not None and window.count >= limit:
                    remaining = self.window_seconds - (
                        now - window.started_at
                    )
                    return RateLimitRejection(
                        dimension=dimension,
                        retry_after_seconds=max(1, math.ceil(remaining)),
                    )
            for dimension, identity, _limit in policies:
                key = (dimension, identity)
                window = active.get(key)
                if window is None:
                    active[key] = _Window(started_at=now, count=1)
                else:
                    window.count += 1
        return None
