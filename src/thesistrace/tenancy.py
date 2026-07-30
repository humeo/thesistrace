from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

_verified_subject: ContextVar[str | None] = ContextVar(
    "thesistrace_verified_subject",
    default=None,
)
_service_workspace: ContextVar[str | None] = ContextVar(
    "thesistrace_service_workspace",
    default=None,
)


def verified_subject() -> str | None:
    return _verified_subject.get()


def service_workspace() -> str | None:
    return _service_workspace.get()


@contextmanager
def authenticated_subject(subject: str) -> Iterator[None]:
    token: Token[str | None] = _verified_subject.set(subject)
    try:
        yield
    finally:
        _verified_subject.reset(token)


@contextmanager
def workspace_execution(workspace_id: str) -> Iterator[None]:
    token: Token[str | None] = _service_workspace.set(workspace_id)
    try:
        yield
    finally:
        _service_workspace.reset(token)
