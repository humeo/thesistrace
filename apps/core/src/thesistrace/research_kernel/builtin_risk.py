"""Built-in Close policies observe the shared account and produce local caps."""

from decimal import Decimal, localcontext
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from thesistrace.research_kernel.numeric import ACCOUNTING_CONTEXT, canonical_decimal


class BuiltinRiskModule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: Literal["builtin_risk/v1"]
    stop_loss_threshold: float | None = Field(
        default=None, gt=0, lt=1, allow_inf_nan=False, exclude_if=lambda value: value is None,
    )
    maximum_holding_sessions: StrictInt | None = Field(
        default=None, ge=1, exclude_if=lambda value: value is None,
    )

    @model_validator(mode="after")
    def require_enabled_policy(self):
        if self.stop_loss_threshold is None and self.maximum_holding_sessions is None:
            raise ValueError("builtin_risk requires at least one enabled policy")
        return self

    def holding_observations(self, account):
        observations = self.stop_loss_observations(account)
        if self.maximum_holding_sessions is not None:
            observations.extend({
                "reason": "maximum_holding_period",
                "instrument_id": position["instrument_id"],
                "execution_shares": position["execution_shares"],
                "holding_age": position["holding_age"],
                "maximum_holding_sessions": self.maximum_holding_sessions,
            } for position in account["positions"]
                if position["holding_age"] >= self.maximum_holding_sessions)
        return observations

    def stop_loss_observations(self, account):
        if self.stop_loss_threshold is None:
            return []
        threshold = Decimal(str(self.stop_loss_threshold))
        observations = []
        with localcontext(ACCOUNTING_CONTEXT):
            for position in account["positions"]:
                cost = Decimal(position["remaining_acquisition_cost_cny"])
                value = (Decimal(position["adjusted_units"])
                         * Decimal(position["last_close_adjusted_price"]))
                if cost > 0 and value <= cost * (1 - threshold):
                    observations.append({
                        "reason": "stop_loss",
                        "instrument_id": position["instrument_id"],
                        "remaining_acquisition_cost_cny": canonical_decimal(cost),
                        "close_market_value_cny": canonical_decimal(value),
                        "holding_return": canonical_decimal(value / cost - 1),
                        "stop_loss_threshold": canonical_decimal(threshold),
                        "execution_shares": position["execution_shares"],
                        "holding_age": position["holding_age"],
                    })
        return observations
