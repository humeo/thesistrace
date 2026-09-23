"""One validated daily decision handed to the shared execution account."""

from dataclasses import dataclass

from thesistrace.research_kernel.framework_evidence import FrameworkEvidence
from thesistrace.research_kernel.terminal_state_schema import PendingTarget


@dataclass(frozen=True)
class DailyDecision:
    state: dict[str, object]
    target: PendingTarget | None
    diagnostics: tuple[dict[str, object], ...]
    framework: FrameworkEvidence | None = None


def program_target(output, context, contract_checksum) -> PendingTarget | None:
    if output is None:
        return None
    if (type(output) is not dict
            or not {"reason", "allocation", "position_limits"} <= set(output)
            or set(output) - {"reason", "allocation", "position_limits", "maximum_stock_exposure"}):
        raise ValueError("Strategy output requires reason, allocation, position_limits")
    target = PendingTarget.model_validate({
        **output, "decision_session": context["session"],
        "execution": "next_research_session_open", "contract_checksum": contract_checksum,
    })
    holdings = {item["instrument_id"]: item["execution_shares"]
                for item in context["account"]["positions"]}
    visible = set(holdings) | {item["instrument_id"] for item in context["candidates"]}
    if not target.instrument_ids <= visible:
        raise ValueError("Strategy target contains an unknown or unavailable instrument")
    if any(item not in holdings or maximum > holdings[item]
           for item, maximum in target.position_limits.items()):
        raise ValueError("Strategy local target must reduce an actual holding")
    return target
