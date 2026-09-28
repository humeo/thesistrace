export type PythonProgram = { source: string };
export type ProgramInputs = { programSource: string };
export type ProgramInputField = keyof ProgramInputs;
export const programInputFields: ProgramInputField[] = ["programSource"];

export function emptyProgramInputs(): ProgramInputs { return { programSource: "" }; }
export function programSpec(input: ProgramInputs): PythonProgram { return { source: input.programSource }; }
export function programDraft(program: PythonProgram): ProgramInputs { return { programSource: program.source }; }
export function programInputIssues(input: ProgramInputs): { field: ProgramInputField; code: "programSource" }[] {
  return !input.programSource.trim() || new TextEncoder().encode(input.programSource).byteLength > 65536
    ? [{ field: "programSource", code: "programSource" }] : [];
}

export const DIRECT_EXAMPLE = `from quantgrove import Strategy

class Momentum(Strategy):
    def on_close(self, data, account):
        lookback = 10
        improvement = 0.01
        prices = data.close_prices(lookback)
        if len(prices.sessions) < lookback:
            return None

        scores = {
            stock: closes[-1] / closes[0] - 1
            for stock, closes in prices.items()
            if closes[0] is not None and closes[-1] is not None and closes[0] > 0
        }
        eligible = [stock for stock in data.candidates if stock in scores]
        if not eligible:
            return None

        best = max(eligible, key=lambda stock: (scores[stock], stock))
        held = [position["instrument_id"] for position in account.positions]
        held_score = max((scores.get(stock, -1) for stock in held), default=-1)
        if best not in held and (not held or scores[best] > held_score + improvement):
            return self.target_weights({best: 1.0})
        return None
`;
