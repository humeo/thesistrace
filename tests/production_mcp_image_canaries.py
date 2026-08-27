from __future__ import annotations

READ_TOKEN = "mcp-image-read-token-canary"
ACTION_TOKEN = "mcp-image-action-token-canary"
SUBJECT = "image-smoke-researcher"
HYPOTHESIS = "mcp-image-hypothesis-canary"
FORMULA = "rank(close) + 0.123456789"

SENSITIVE_CANARIES = (
    READ_TOKEN,
    ACTION_TOKEN,
    SUBJECT,
    HYPOTHESIS,
    FORMULA,
    "observability-access-canary",
    "observability-secret-canary",
    "observability-request-canary",
)
