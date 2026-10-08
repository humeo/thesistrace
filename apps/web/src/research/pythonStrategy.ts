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

export const DIRECT_EXAMPLE = `import numpy as np
from quantgrove import Targets


def compute(data, state):
    lookback = 60
    close = data.history("price.close.adjusted", lookback=lookback)
    now, before = close[:, lookback:], close[:, :-lookback]
    valid = data.eligible & np.isfinite(now) & np.isfinite(before) & (before > 0)
    scores = np.full(now.shape, -np.inf)
    np.divide(now, before, out=scores, where=valid)
    scores -= 1
    order = np.argsort(-scores, axis=0, kind="stable")[:30]
    selected = np.zeros(scores.shape, dtype=bool)
    np.put_along_axis(selected, order, True, axis=0)
    selected &= valid
    return Targets.equal_weight(selected, priority=scores, update=(data.session_index % 5 == 0) & selected.any(axis=0))
`;
