"""Actionable input diagnostics without echoing caller-controlled values or keys."""

from pydantic import ValidationError

from thesistrace.research_agent.models import ResearchAgentInputIssue

_SAFE_ERROR_TYPES = frozenset({
    "missing", "extra_forbidden", "string_type", "int_type", "float_type", "bool_type",
    "dict_type", "list_type", "string_too_short", "string_too_long", "too_short", "too_long",
    "greater_than", "greater_than_equal", "less_than", "less_than_equal", "multiple_of",
    "literal_error", "string_pattern_mismatch", "finite_number",
})
_SAFE_VALUE_ERRORS = frozenset({
    "Python Portfolio cannot contain builtin Portfolio settings",
    "Python Signal cannot contain builtin Alpha settings",
    "Research end date must not precede start date",
    "natural date must be an ISO YYYY-MM-DD string",
    "Initial Cash must be positive and at most 1000000000 CNY",
    "Simulation cost must be a decimal string",
    "Simulation cost must be finite and non-negative",
    "Price slippage must be less than 10000 basis points",
    "Program source exceeds 65536 UTF-8 bytes",
    "A Strategy Sweep must use one strategy mode",
    "A Strategy Sweep must use one Alpha mode",
    "Direct Strategy Sweep cannot contain shared Alpha settings",
    "Python Signal Sweep cannot contain shared Alpha settings",
})


def input_issues(
    error: ValidationError, schema: dict[str, object],
) -> list[ResearchAgentInputIssue]:
    fields: set[str] = set()

    def collect(value: object) -> None:
        if isinstance(value, dict):
            properties = value.get("properties")
            if isinstance(properties, dict):
                fields.update(properties)
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(schema)
    issues = []
    for entry in error.errors(include_input=False, include_context=False, include_url=False)[:20]:
        code = entry["type"]
        message = "Invalid value; follow the field and cross-field constraints in inputSchema."
        if code in _SAFE_ERROR_TYPES:
            message = entry["msg"]
        elif code == "value_error":
            detail = entry["msg"].removeprefix("Value error, ")
            if detail in _SAFE_VALUE_ERRORS:
                message = detail
        elif code in {"union_tag_invalid", "union_tag_not_found"}:
            message = "Select a supported discriminator value from inputSchema."
        issues.append(ResearchAgentInputIssue(
            path=[part if isinstance(part, int) or part in fields else "*"
                  for part in entry["loc"][:16]],
            code=code,
            message=message[:200],
        ))
    return issues
