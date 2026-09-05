from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from time import perf_counter_ns
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from mcp.server.auth.middleware.auth_context import AuthContextMiddleware, get_access_token
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend, RequireAuthMiddleware
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.routes import build_resource_metadata_url, create_protected_resource_routes
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl, TypeAdapter
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.responses import JSONResponse
from starlette.routing import BaseRoute
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from thesistrace.operational_events import OperationalEventWriter
from thesistrace.research_agent.mcp_server import (
    RESEARCH_AGENT_MAX_WIRE_REQUEST_BYTES,
    create_research_agent_mcp_server,
)
from thesistrace.research_agent.models import ResearchAgentAuthority, ResearchAgentScope
from thesistrace.research_agent.registry import (
    RESEARCH_AGENT_TOOL_NAMES,
    ResearchAgentCapabilityRegistry,
    ResearchAgentModules,
)

RESEARCH_AGENT_MAX_HTTP_BODY_FRAMES = 256


@dataclass(frozen=True)
class ResearchAgentHTTPConfiguration:
    token_verifier: TokenVerifier
    issuer_url: AnyHttpUrl | str
    resource_server_url: AnyHttpUrl | str
    deployment_tool_allowlist: frozenset[str]
    allowed_hosts: tuple[str, ...]
    supported_scopes: frozenset[ResearchAgentScope]
    allowed_origins: tuple[str, ...] = ()
    allow_loopback_http: bool = False

    def __post_init__(self) -> None:
        if not callable(getattr(self.token_verifier, "verify_token", None)):
            raise ValueError("Research Agent HTTP requires a token verifier")
        issuer_url = _http_url(self.issuer_url, field="issuer_url")
        resource_server_url = _http_url(
            self.resource_server_url,
            field="resource_server_url",
        )
        issuer_parts = urlsplit(str(issuer_url))
        if issuer_parts.scheme != "https" and not (
            self.allow_loopback_http
            and issuer_parts.scheme == "http"
            and issuer_parts.hostname in {"localhost", "127.0.0.1", "::1"}
        ):
            raise ValueError("Research Agent HTTP issuer_url must use HTTPS")
        if issuer_parts.query or issuer_parts.fragment:
            raise ValueError("Research Agent HTTP issuer_url cannot contain query or fragment")
        resource_parts = urlsplit(str(resource_server_url))
        if resource_parts.scheme != "https" and not (
            self.allow_loopback_http
            and resource_parts.scheme == "http"
            and resource_parts.hostname in {"localhost", "127.0.0.1", "::1"}
        ):
            raise ValueError("Research Agent HTTP resource_server_url must use HTTPS")
        if resource_parts.path != "/mcp" or resource_parts.query or resource_parts.fragment:
            raise ValueError("Research Agent HTTP resource_server_url must end at /mcp")
        unknown_tools = self.deployment_tool_allowlist - RESEARCH_AGENT_TOOL_NAMES
        if unknown_tools:
            raise ValueError(
                f"unknown Research Agent deployment tools: {', '.join(sorted(unknown_tools))}"
            )
        if not self.allowed_hosts or any(not value.strip() for value in self.allowed_hosts):
            raise ValueError("Research Agent HTTP requires explicit allowed_hosts")
        if any(not value.strip() for value in self.allowed_origins):
            raise ValueError("Research Agent HTTP allowed_origins cannot contain blanks")
        if not self.supported_scopes:
            raise ValueError("Research Agent HTTP requires explicit supported_scopes")
        object.__setattr__(self, "issuer_url", issuer_url)
        object.__setattr__(self, "resource_server_url", resource_server_url)


@dataclass(frozen=True)
class ResearchAgentHTTPTransport:
    app: ASGIApp
    session_manager: StreamableHTTPSessionManager
    metadata_routes: tuple[BaseRoute, ...]


class _ResearcherBoundTokenVerifier:
    def __init__(self, delegate: TokenVerifier) -> None:
        self._delegate = delegate

    async def verify_token(self, token: str) -> AccessToken | None:
        access_token = await self._delegate.verify_token(token)
        if access_token is None:
            return None
        try:
            _token_researcher_id(access_token)
        except ValueError:
            return None
        return access_token


class _BoundedMCPRequestBody:
    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not _is_mcp_call(scope):
            await self._app(scope, receive, send)
            return
        content_length = _content_length(scope)
        if content_length is not None and content_length > RESEARCH_AGENT_MAX_WIRE_REQUEST_BYTES:
            await _request_too_large_response(scope, receive, send)
            return

        body = bytearray()
        frames = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                await self._app(scope, _replay_once(message, receive), send)
                return
            frames += 1
            body.extend(message.get("body", b""))
            if (
                len(body) > RESEARCH_AGENT_MAX_WIRE_REQUEST_BYTES
                or frames > RESEARCH_AGENT_MAX_HTTP_BODY_FRAMES
            ):
                await _request_too_large_response(scope, receive, send)
                return
            if not message.get("more_body", False):
                break
        await self._app(
            scope,
            _replay_once(
                {
                    "type": "http.request",
                    "body": bytes(body),
                    "more_body": False,
                },
                receive,
            ),
            send,
        )


def create_research_agent_http_transport(
    configuration: ResearchAgentHTTPConfiguration,
    *,
    modules: Callable[[], ResearchAgentModules],
    event_sink: OperationalEventWriter,
    monotonic_ns: Callable[[], int] = perf_counter_ns,
    trace_id_factory: Callable[[], str] | None = None,
) -> ResearchAgentHTTPTransport:
    selected_trace_id_factory = trace_id_factory or _new_trace_id

    def authenticated_subject(_context: object) -> str:
        token = get_access_token()
        if token is None:
            raise RuntimeError("authenticated Research Agent token is unavailable")
        if token.subject is None:
            raise RuntimeError("authenticated Research Agent subject is unavailable")
        return token.subject

    def authenticated_researcher_id(_context: object) -> UUID:
        token = get_access_token()
        if token is None:
            raise RuntimeError("authenticated Research Agent token is unavailable")
        return _token_researcher_id(token)

    def registry_factory(context: object) -> ResearchAgentCapabilityRegistry:
        token = get_access_token()
        if token is None:
            raise RuntimeError("authenticated Research Agent token is unavailable")
        granted_scopes = frozenset(
            scope for scope in configuration.supported_scopes if scope.value in token.scopes
        )
        return ResearchAgentCapabilityRegistry(
            authority=ResearchAgentAuthority(
                subject=authenticated_subject(context),
                researcher_id=authenticated_researcher_id(context),
                scopes=granted_scopes,
            ),
            modules=modules(),
            allowed_tools=configuration.deployment_tool_allowlist,
        )

    server = create_research_agent_mcp_server(
        registry_factory,
        event_sink=event_sink,
        monotonic_ns=monotonic_ns,
        subject_factory=authenticated_subject,
        trace_id_factory=selected_trace_id_factory,
        transport="streamable_http",
    )
    manager = StreamableHTTPSessionManager(
        server,
        json_response=True,
        stateless=True,
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(configuration.allowed_hosts),
            allowed_origins=list(configuration.allowed_origins),
        ),
    )
    metadata_url = build_resource_metadata_url(configuration.resource_server_url)
    bounded_manager: ASGIApp = _BoundedMCPRequestBody(manager.handle_request)
    protected_app: ASGIApp = RequireAuthMiddleware(
        bounded_manager,
        required_scopes=[],
        resource_metadata_url=metadata_url,
    )
    protected_app = AuthContextMiddleware(protected_app)
    protected_app = AuthenticationMiddleware(
        protected_app,
        backend=BearerAuthBackend(_ResearcherBoundTokenVerifier(configuration.token_verifier)),
    )
    metadata_routes: Sequence[BaseRoute] = create_protected_resource_routes(
        resource_url=configuration.resource_server_url,
        authorization_servers=[configuration.issuer_url],
        scopes_supported=[
            scope.value
            for scope in sorted(
                configuration.supported_scopes,
                key=lambda scope: scope.value,
            )
        ],
        resource_name="ThesisTrace Research Agent",
    )
    return ResearchAgentHTTPTransport(
        app=protected_app,
        session_manager=manager,
        metadata_routes=tuple(metadata_routes),
    )


def _http_url(value: Any, *, field: str) -> AnyHttpUrl:
    try:
        return TypeAdapter(AnyHttpUrl).validate_python(value)
    except ValueError as error:
        raise ValueError(f"Research Agent HTTP {field} must be an HTTP URL") from error


def _token_researcher_id(token: AccessToken) -> UUID:
    if token.subject is None:
        raise ValueError("Research Agent access token must bind a Researcher subject")
    try:
        return UUID(token.subject)
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError("Research Agent access token subject must be a Researcher UUID") from error


def _new_trace_id() -> str:
    return f"trace_{uuid4().hex}"


def _is_mcp_call(scope: Scope) -> bool:
    return scope["type"] == "http" and scope.get("method") == "POST" and scope.get("path") == "/mcp"


def _content_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", ()):
        if name.lower() != b"content-length":
            continue
        try:
            parsed = int(value)
        except ValueError:
            return None
        return max(0, parsed)
    return None


def _replay_once(message: Message, receive: Receive) -> Receive:
    pending: Message | None = message

    async def replay() -> Message:
        nonlocal pending
        if pending is not None:
            current = pending
            pending = None
            return current
        return await receive()

    return replay


async def _request_too_large_response(
    scope: Scope,
    receive: Receive,
    send: Send,
) -> None:
    response = JSONResponse(
        {
            "jsonrpc": "2.0",
            "id": None,
            "error": {
                "code": -32600,
                "message": "Request exceeds server limit",
            },
        },
        status_code=413,
    )
    await response(scope, receive, send)
