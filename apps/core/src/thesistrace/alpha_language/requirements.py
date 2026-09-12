"""Joint data and resource requirements of the expressions in one research definition."""

from dataclasses import dataclass

from thesistrace.alpha_language.models import CompiledAlpha
from thesistrace.research_kernel.common_inputs import requires_common_industry


@dataclass(frozen=True)
class ExpressionRequirements:
    field_bindings: dict[str, str]
    effective_lookback: int
    node_count: int
    depth: int
    estimated_work: int
    require_industry: bool


def expression_requirements(*expressions: CompiledAlpha) -> ExpressionRequirements:
    if not expressions:
        raise ValueError('Research needs at least one expression')
    return ExpressionRequirements(
        field_bindings={
            field_id: identifier
            for expression in expressions
            for identifier, field_id in expression.field_ids_by_identifier.items()
        },
        effective_lookback=max(expression.effective_lookback for expression in expressions),
        node_count=sum(expression.node_count for expression in expressions),
        depth=max(expression.depth for expression in expressions),
        estimated_work=sum(expression.estimated_work for expression in expressions),
        require_industry=any(
            requires_common_industry(expression.expression) for expression in expressions
        ),
    )
