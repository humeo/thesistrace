"""Built-in Close policies observe the shared account and produce local caps."""

from decimal import Decimal, localcontext
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from thesistrace.research_kernel.numeric import ACCOUNTING_CONTEXT, canonical_decimal


class BuiltinRiskModule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: Literal["builtin_risk/v1"]
    stop_loss_threshold: float = Field(gt=0, lt=1, allow_inf_nan=False)

    def stop_loss_observations(self, account):
        threshold = Decimal(str(self.stop_loss_threshold))
        observations = []
        with localcontext(ACCOUNTING_CONTEXT):
            for position in account["positions"]:
                cost = Decimal(position["remaining_acquisition_cost_cny"])
                value = (Decimal(position["adjusted_units"])
                         * Decimal(position["last_close_adjusted_price"]))
                if cost > 0 and value <= cost * (1 - threshold):
                    observations.append({
                        "instrument_id": position["instrument_id"],
                        "remaining_acquisition_cost_cny": canonical_decimal(cost),
                        "close_market_value_cny": canonical_decimal(value),
                        "holding_return": canonical_decimal(value / cost - 1),
                        "stop_loss_threshold": canonical_decimal(threshold),
                        "execution_shares": position["execution_shares"],
                        "holding_age": position["holding_age"],
                    })
        return observations
