import type { FrameworkStage } from "./frameworkModules";
import type { ProgramInputs } from "./pythonStrategy";

const sources: Record<FrameworkStage, string> = {
  universe_selection: `from quantgrove import UniverseSelection

class SelectCandidates(UniverseSelection):
    def on_close(self, data, account):
        return self.select(data.candidates)
`,
  alpha: `from quantgrove import Alpha

class MomentumSignals(Alpha):
    def on_close(self, data, account):
        lookback = 10
        prices = data.close_prices(lookback)
        if len(prices.sessions) < lookback:
            return None
        scores = {
            stock: closes[-1] / closes[0] - 1
            for stock, closes in prices.items()
            if stock in data.candidates and closes[0] is not None
            and closes[-1] is not None and closes[0] > 0
        }
        return self.signals(scores, valid_for_sessions=2)
`,
  portfolio_construction: `from quantgrove import PortfolioConstruction

class BestSignal(PortfolioConstruction):
    def on_close(self, data, account):
        improvement = 0.01
        scores = {row["instrument_id"]: row["value"] for row in data.framework["signals"]}
        if not scores:
            return None
        best = max(scores, key=lambda stock: (scores[stock], stock))
        held = [row["instrument_id"] for row in account.positions]
        held_score = max((scores.get(stock, -1) for stock in held), default=-1)
        if best not in held and (not held or scores[best] > held_score + improvement):
            return self.target_weights({best: 1.0})
        return None
`,
  risk_management: `from quantgrove import RiskManagement

class ExitAfterTwentySessions(RiskManagement):
    def on_close(self, data, account):
        maximum_holding_sessions = 20
        exits = {row["instrument_id"]: 0 for row in account.positions
                 if row["holding_age"] >= maximum_holding_sessions}
        if exits:
            return self.limit_positions(exits)
        return None
`,
};

export function frameworkExample(stage: FrameworkStage): ProgramInputs {
  return { programSource: sources[stage] };
}
