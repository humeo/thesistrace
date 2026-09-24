import Decimal from "decimal.js";

export const costFields = [
  { key: "commission_rate_all_in", label: "Buy/sell commission rate", help: "0.0003 means 0.03% of each fill." },
  { key: "commission_min_cny", label: "Minimum commission per child order (CNY)", help: "Applied separately to each filled child order, including split orders." },
  { key: "stamp_duty_sell_rate", label: "Sell stamp duty rate", help: "0.0005 means 0.05%. Charged only on sells." },
  { key: "transfer_fee_rate", label: "Buy/sell transfer fee rate", help: "0.00001 means 0.001% of each fill." },
  { key: "slippage_bps", label: "Price slippage (basis points)", help: "10 bp raises buy prices and lowers sell prices by 0.1%. Must be below 10,000 bp." },
] as const;

export type CostField = typeof costFields[number]["key"];
export type SimulationCosts = Record<CostField, string>;

export function defaultSimulationCosts(): SimulationCosts {
  return { commission_rate_all_in: "0.0003", commission_min_cny: "5",
    stamp_duty_sell_rate: "0.0005", transfer_fee_rate: "0.00001", slippage_bps: "0" };
}

export function costInputError(field: CostField, value: string): string | undefined {
  try {
    if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value) || value.length > 128) throw new Error();
    const amount = new Decimal(value);
    if (!amount.isFinite() || amount.lt(0)) throw new Error();
    if (field === "slippage_bps" && amount.gte(10000)) return "Slippage must be below 10,000 basis points.";
  } catch { return "Enter a finite, non-negative decimal value."; }
}

export function readCostInputs(value: unknown): SimulationCosts | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const costs = value as Record<string, unknown>;
  if (Object.keys(costs).length !== costFields.length || costFields.some(({ key }) =>
    typeof costs[key] !== "string" || costs[key].length > 128)) return null;
  return Object.fromEntries(costFields.map(({ key }) => [key, costs[key]])) as SimulationCosts;
}
