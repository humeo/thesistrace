import json
import logging
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

MAX_LOG_MESSAGE_BYTES = 2048
EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
WORKSPACE_ID = re.compile(r"\bworkspace_[0-9a-f]+\b", re.IGNORECASE)
AUTHORIZATION_HEADER = re.compile(
    r"(?i)[\"']?\bauthorization\b[\"']?\s*[:=]\s*[\"']?"
    r"(?:bearer|basic)\s+[^\"',;}\s]+[\"']?"
)
SECRET_ASSIGNMENT = re.compile(
    r"(?i)[\"']?\b([A-Za-z0-9_-]*(?:token|password|secret|api[_-]?key))"
    r"\b[\"']?\s*[:=]\s*"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
RESEARCH_ASSIGNMENT = re.compile(
    r"(?i)[\"']?\b(expression|alpha)\b[\"']?\s*[:=]\s*.*"
)
ALPHA_FIELD = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*")
_configured = False
class JsonLogFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        message = sanitize_text(record.getMessage())
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "service": self.service,
            "event": message,
        }
        if record.exc_info and record.exc_info[0] is not None:
            payload["exception_type"] = record.exc_info[0].__name__
        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            payload["trace_id"] = trace.format_trace_id(span_context.trace_id)
            payload["span_id"] = trace.format_span_id(span_context.span_id)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def sanitize_text(value: str) -> str:
    sanitized = EMAIL.sub("[redacted-email]", value)
    sanitized = WORKSPACE_ID.sub("[redacted-workspace]", sanitized)
    sanitized = AUTHORIZATION_HEADER.sub("authorization=[redacted]", sanitized)
    sanitized = SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[redacted]", sanitized)
    sanitized = RESEARCH_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}=[redacted]",
        sanitized,
    )
    sanitized = ALPHA_FIELD.sub("[redacted-expression]", sanitized)
    encoded = sanitized.encode("utf-8")
    if len(encoded) <= MAX_LOG_MESSAGE_BYTES:
        return sanitized
    return encoded[:MAX_LOG_MESSAGE_BYTES].decode("utf-8", errors="ignore") + "…"


def configure_observability(service: str) -> None:
    global _configured
    if _configured:
        return
    _configured = True
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter(service))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": service,
                "service.version": os.environ.get("THESISTRACE_RELEASE_VERSION", "unknown"),
            }
        )
    )
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=endpoint,
                insecure=endpoint.startswith("http://"),
            ),
            max_queue_size=2048,
            max_export_batch_size=512,
            schedule_delay_millis=5000,
            export_timeout_millis=3000,
        )
    )
    trace.set_tracer_provider(provider)


@contextmanager
def operation_span(
    kind: str,
    operation: str,
    *,
    mark_success: bool = True,
) -> Iterator[Any]:
    tracer = trace.get_tracer("thesistrace.hosted")
    with tracer.start_as_current_span(
        f"{kind}.operation",
        attributes={
            "thesistrace.span.kind": kind,
            "thesistrace.operation": operation,
        },
    ) as span:
        try:
            yield span
        except BaseException as error:
            span.set_attribute("exception.type", type(error).__name__)
            span.set_status(Status(StatusCode.ERROR))
            raise
        else:
            if mark_success:
                span.set_status(Status(StatusCode.OK))


def instrument_http(app: FastAPI) -> None:
    @app.middleware("http")
    async def trace_http(request: Request, call_next):
        with operation_span("http", "request", mark_success=False) as span:
            span.set_attribute("http.request.method", request.method)
            response = await call_next(request)
            span.set_attribute("http.response.status_code", response.status_code)
            if response.status_code >= 500:
                span.set_status(Status(StatusCode.ERROR))
            else:
                span.set_status(Status(StatusCode.OK))
            return response
