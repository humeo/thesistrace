import contextvars
from collections.abc import Callable
from threading import Event, Lock, Thread

from temporalio import activity

from thesistrace.activity_contract import CooperativeActivityCancellation


class ActivityHeartbeat:
    def __init__(
        self,
        interval: float = 10.0,
        *,
        on_cancel: Callable[[], None] | None = None,
    ) -> None:
        self.interval = interval
        self.on_cancel = on_cancel
        self.stop_event = Event()
        self.cancel_lock = Lock()
        self.cancel_recorded = False
        context = contextvars.copy_context()
        self.thread = Thread(
            target=lambda: context.run(self._run),
            name="heavy-activity-heartbeat",
            daemon=True,
        )

    def __enter__(self) -> "ActivityHeartbeat":
        activity.heartbeat({"stage": "started"})
        self.thread.start()
        return self

    def checkpoint(self, stage: str) -> None:
        if activity.is_cancelled():
            self._record_cancellation()
            raise CooperativeActivityCancellation
        activity.heartbeat({"stage": stage})

    def __exit__(self, _type, _value, _traceback) -> None:
        self.stop_event.set()
        self.thread.join(timeout=self.interval + 1)

    def _run(self) -> None:
        while not self.stop_event.wait(self.interval):
            if activity.is_cancelled():
                self._record_cancellation()
                return
            activity.heartbeat({"stage": "running"})

    def _record_cancellation(self) -> None:
        if self.on_cancel is None:
            return
        with self.cancel_lock:
            if self.cancel_recorded:
                return
            self.on_cancel()
            self.cancel_recorded = True
