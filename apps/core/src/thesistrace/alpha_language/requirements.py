"""Joint data and resource requirements of the expressions in one research definition."""

from dataclasses import dataclass

from thesistrace.alpha_language.models import CompiledAlpha
from thesistrace.research_kernel.common_inputs import CLOSE_FIELD_ID, requires_common_industry
from thesistrace.research_kernel.portfolio_weighting import PortfolioWeighting


@dataclass(frozen=True)
class ExpressionRequirements:
    field_bindings: dict[str, str]
    effective_lookback: int
    node_count: int
    depth: int
    estimated_work: int
    require_industry: bool


def expression_requirements(
    *expressions: CompiledAlpha,
    weighting: PortfolioWeighting = "equal_weight",
    volatility_window: int = 20,
) -> ExpressionRequirements:
    if not expressions:
        raise ValueError('Research needs at least one expression')
    inverse = weighting == "inverse_volatility"
    if type(volatility_window) is not int or not 1 <= volatility_window <= 252:
        raise ValueError("Invalid volatility window")
    return ExpressionRequirements(
        field_bindings={**{
            field_id: identifier
            for expression in expressions
            for identifier, field_id in expression.field_ids_by_identifier.items()
        }, **({CLOSE_FIELD_ID: "close"} if inverse else {})},
        effective_lookback=max(
            max(expression.effective_lookback for expression in expressions),
            volatility_window if inverse else 0,
        ),
        node_count=sum(expression.node_count for expression in expressions),
        depth=max(expression.depth for expression in expressions),
        estimated_work=(sum(expression.estimated_work for expression in expressions)
                        + (4 * volatility_window if inverse else 0)),
        require_industry=any(
            requires_common_industry(expression.expression) for expression in expressions
        ),
    )
