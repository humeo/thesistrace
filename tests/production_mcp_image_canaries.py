from __future__ import annotations

READ_TOKEN = "mcp-image-read-token-canary"
ACTION_TOKEN = "mcp-image-action-token-canary"
SUBJECT = "018f6f7e-8342-7c9a-a4df-9a86147d2e02"
HYPOTHESIS = "mcp-image-hypothesis-canary"
FORMULA = "rank(close) + 0.123456789"

SENSITIVE_CANARIES = (
    READ_TOKEN,
    ACTION_TOKEN,
    SUBJECT,
    HYPOTHESIS,
    FORMULA,
    "observability-access-canary",
    "observability-outage-canary",
    "observability-secret-canary",
    "observability-request-canary",
    "0f3d7a91c4e6482b8d5f106a79c2e4b3",
    "correct-horse-battery-staple",
    "Browser-acceptance-password-2026",
)
