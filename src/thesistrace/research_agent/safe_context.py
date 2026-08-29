from __future__ import annotations

from collections.abc import Collection, Mapping
from hashlib import sha256

from thesistrace.research_agent.models import ResearchAgentToolErrorContext


def safe_tool_call_context(
    tool_name: str,
    arguments: Mapping[str, object],
    *,
    known_tool_names: Collection[str],
    structured_response: object = None,
) -> ResearchAgentToolErrorContext:
    values: dict[str, str] = {
        "tool_name": (
            tool_name
            if tool_name in known_tool_names
            else digested_identifier("tool", tool_name)
        )
    }
    for field in ("run_id", "batch_id", "track_id"):
        canonical = _canonical_response_identifier(
            field,
            tool_name,
            structured_response,
        )
        if canonical is not None:
            values[field] = canonical
            continue
        supplied = arguments.get(field)
        if isinstance(supplied, str) and supplied:
            values[field] = digested_identifier(field, supplied)
    request_id = arguments.get("request_id")
    if isinstance(request_id, str) and request_id:
        values["request_id"] = digested_identifier("request", request_id.strip())
    return ResearchAgentToolErrorContext.model_validate(values)


def digested_identifier(kind: str, value: str) -> str:
    digest = sha256(value.encode("utf-8", errors="surrogatepass")).hexdigest()[:32]
    return f"{kind}_{digest}"


def _canonical_response_identifier(
    field: str,
    tool_name: str,
    structured_response: object,
) -> str | None:
    if not isinstance(structured_response, dict):
        return None
    direct = structured_response.get(field)
    if isinstance(direct, str) and direct:
        return direct
    resource_field = {
        "get_research_run": "run_id",
        "get_research_batch": "batch_id",
        "get_daily_track": "track_id",
    }.get(tool_name)
    identifier = structured_response.get("id")
    if resource_field == field and isinstance(identifier, str) and identifier:
        return identifier
    nested = structured_response.get(field.removesuffix("_id"))
    if isinstance(nested, dict):
        identifier = nested.get("id")
        if isinstance(identifier, str) and identifier:
            return identifier
    return None
