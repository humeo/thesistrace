from __future__ import annotations

import json
from pathlib import Path

AGENT_CANARIES = json.loads(
    (Path(__file__).parent / "fixtures" / "agent-privacy-canaries.json").read_text()
)

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
    *AGENT_CANARIES.values(),
    "private-timeout-canary",
    "private-provider-canary",
    "private-prompt-canary",
    "private-stream-canary",
    "MALICIOUS_A2UI_SHOULD_NOT_RENDER",
)

CANARY_CATEGORIES = {
    **{value: "existing_private_value" for value in SENSITIVE_CANARIES},
    **{value: category for category, value in AGENT_CANARIES.items()},
}
