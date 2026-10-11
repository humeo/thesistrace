"""Bound actual ingress bytes before an HTTP consumer buffers or parses them."""

from collections.abc import Callable

import anyio
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class BoundedRequestBody:
    def __init__(
        self, app: ASGIApp, *, max_bytes: int, timeout_seconds: float,
        accepts: Callable[[Scope], bool], error_response: Callable[[int, str], Response],
    ) -> None:
        self._app = app
        self._max_bytes = max_bytes
        self._timeout_seconds = timeout_seconds
        self._accepts = accepts
        self._error_response = error_response

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._accepts(scope):
            await self._app(scope, receive, send)
            return
        length = next((value for name, value in scope.get("headers", ())
                       if name.lower() == b"content-length"), None)
        try:
            declared = int(length) if length is not None else 0
        except ValueError:
            declared = 0
        if declared > self._max_bytes:
            await self._error_response(413, "Request exceeds server limit")(scope, receive, send)
            return
        body = bytearray()
        oversized = False
        try:
            with anyio.fail_after(self._timeout_seconds):
                while True:
                    await anyio.lowlevel.checkpoint()
                    message = await receive()
                    if message["type"] != "http.request":
                        break
                    chunk = message.get("body", b"")
                    if len(body) + len(chunk) > self._max_bytes:
                        oversized = True
                        break
                    body.extend(chunk)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            await self._error_response(408, "Request body read timed out")(scope, receive, send)
            return
        if oversized:
            await self._error_response(413, "Request exceeds server limit")(scope, receive, send)
            return
        if message["type"] == "http.request":
            message = {"type": "http.request", "body": bytes(body), "more_body": False}
        body.clear()
        pending: Message | None = message

        async def replay() -> Message:
            nonlocal pending
            if pending is not None:
                current, pending = pending, None
                return current
            return await receive()

        await self._app(scope, replay, send)
