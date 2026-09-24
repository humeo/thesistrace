"""Cumulative Close take-profit intent in stable adjusted holding units."""

from decimal import Decimal, InvalidOperation, localcontext

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

from thesistrace.research_kernel.numeric import ACCOUNTING_CONTEXT, canonical_decimal


class TakeProfitCycle(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    holding_cycle_started_session: StrictStr = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    baseline_adjusted_units: StrictStr = Field(max_length=128)
    baseline_execution_shares: StrictInt = Field(gt=0)
    highest_triggered_tier: StrictInt = Field(ge=0, lt=100)
    executed_reduction_units: StrictStr = Field(max_length=128)
    last_adjusted_units: StrictStr = Field(max_length=128)
    last_execution_shares: StrictInt = Field(gt=0)

    @model_validator(mode="after")
    def quantities_are_possible(self):
        values = []
        for field in ("baseline_adjusted_units", "executed_reduction_units", "last_adjusted_units"):
            try:
                value = Decimal(getattr(self, field))
            except InvalidOperation as error:
                raise ValueError(f"Invalid take-profit {field}") from error
            if (not value.is_finite() or value < 0
                    or canonical_decimal(value) != getattr(self, field)):
                raise ValueError(f"Invalid take-profit {field}")
            values.append(value)
        baseline, executed, remaining = values
        if baseline <= 0 or not 0 < remaining <= baseline or executed > baseline:
            raise ValueError("Invalid take-profit baseline or actual progress")
        return self


class TakeProfitState(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    take_profit_cycles: dict[StrictStr, TakeProfitCycle] = Field(max_length=3000)


def take_profit_decision(*, tiers, account, previous, fills):
    """Reconcile actual sales before computing the next Close's local caps."""
    state, limits, observations = {}, {}, []
    previous_cycles = (TakeProfitState.model_validate(previous).model_dump()["take_profit_cycles"]
                       if previous else {})
    if any(cycle["highest_triggered_tier"] >= len(tiers) for cycle in previous_cycles.values()):
        raise ValueError("Take-profit progress differs from configured tiers")
    sold = {}
    for fill in fills:
        if fill["side"] == "sell":
            item = fill["instrument_id"]
            sold[item] = sold.get(item, 0) + fill["quantity"]
    with localcontext(ACCOUNTING_CONTEXT):
        for position in account["positions"]:
            item = position["instrument_id"]
            units = Decimal(position["adjusted_units"])
            cost = Decimal(position["remaining_acquisition_cost_cny"])
            value = units * Decimal(position["last_close_adjusted_price"])
            holding_return = value / cost - 1 if cost > 0 else Decimal(0)
            reached = [index for index, tier in enumerate(tiers)
                       if holding_return >= Decimal(str(tier.profit_threshold))]
            cycle = previous_cycles.get(item)
            if cycle and cycle["holding_cycle_started_session"] != position[
                "holding_cycle_started_session"
            ]:
                cycle = None
            if cycle is None:
                if not reached:
                    continue
                cycle = {
                    "holding_cycle_started_session": position["holding_cycle_started_session"],
                    "baseline_adjusted_units": canonical_decimal(units),
                    "baseline_execution_shares": position["execution_shares"],
                    "highest_triggered_tier": max(reached),
                    "executed_reduction_units": "0",
                    "last_adjusted_units": canonical_decimal(units),
                    "last_execution_shares": position["execution_shares"],
                }
            else:
                cycle = dict(cycle)
                if item in sold:
                    actual_reduction = max(
                        Decimal(0), Decimal(cycle["last_adjusted_units"]) - units,
                    )
                    cycle["executed_reduction_units"] = canonical_decimal(
                        Decimal(cycle["executed_reduction_units"]) + actual_reduction,
                    )
                if reached:
                    cycle["highest_triggered_tier"] = max(
                        cycle["highest_triggered_tier"], max(reached),
                    )
                cycle["last_adjusted_units"] = canonical_decimal(units)
                cycle["last_execution_shares"] = position["execution_shares"]
            tier = tiers[cycle["highest_triggered_tier"]]
            baseline = Decimal(cycle["baseline_adjusted_units"])
            reduction = Decimal(str(tier.cumulative_reduction))
            target_units = baseline * (1 - reduction)
            # A cap also prevents a simultaneous ordinary proposal buying back
            # a completed reduction. Existing deeper reductions remain intact.
            maximum = min(position["execution_shares"], int(
                target_units * position["execution_shares"] / units,
            ))
            limits[item] = maximum
            state[item] = cycle
            observations.append({
                "reason": "take_profit", "instrument_id": item, "cycle_ended": False,
                "holding_return": canonical_decimal(holding_return),
                "profit_threshold": canonical_decimal(Decimal(str(tier.profit_threshold))),
                "cumulative_reduction": canonical_decimal(reduction),
                "baseline_execution_shares": cycle["baseline_execution_shares"],
                "baseline_adjusted_units": cycle["baseline_adjusted_units"],
                "target_adjusted_units": canonical_decimal(target_units),
                "executed_reduction_units": cycle["executed_reduction_units"],
                "remaining_reduction_units": canonical_decimal(max(Decimal(0), units-target_units)),
                "execution_shares": position["execution_shares"],
                "position_limit": maximum,
            })
        # Full sales and account writeoffs both end a cycle, but only actual
        # fills count as executed reductions. Preserve that distinction in facts.
        for item, cycle in previous_cycles.items():
            if item in state:
                continue
            tier = tiers[cycle["highest_triggered_tier"]]
            baseline = Decimal(cycle["baseline_adjusted_units"])
            planned = baseline * Decimal(str(tier.cumulative_reduction))
            executed = Decimal(cycle["executed_reduction_units"]) + (
                Decimal(cycle["last_adjusted_units"]) * sold.get(item, 0)
                / cycle["last_execution_shares"]
            )
            observations.append({
                "reason": "take_profit", "instrument_id": item, "cycle_ended": True,
                "holding_return": None,
                "profit_threshold": canonical_decimal(Decimal(str(tier.profit_threshold))),
                "cumulative_reduction": canonical_decimal(Decimal(str(tier.cumulative_reduction))),
                "baseline_execution_shares": cycle["baseline_execution_shares"],
                "baseline_adjusted_units": cycle["baseline_adjusted_units"],
                "target_adjusted_units": canonical_decimal(baseline - planned),
                "executed_reduction_units": canonical_decimal(executed),
                "remaining_reduction_units": canonical_decimal(max(Decimal(0), planned-executed)),
                "execution_shares": 0, "position_limit": None,
            })
    return {"take_profit_cycles": state}, limits, observations
