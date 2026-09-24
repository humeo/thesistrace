export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };
export type PythonProgram = {
  source: string;
  parameters: Record<string, JsonValue>;
  data_requirements: { field_ids: string[]; history_sessions: number };
};

export type ProgramInputs = {
  programSource: string;
  programParameters: string;
  programFields: string;
  programHistorySessions: string;
};
export type ProgramInputField = keyof ProgramInputs;
export const programInputFields: ProgramInputField[] = [
  "programSource", "programParameters", "programFields", "programHistorySessions",
];

export function emptyProgramInputs(): ProgramInputs {
  return { programSource: "", programParameters: "", programFields: "", programHistorySessions: "" };
}

export function programSpec(input: ProgramInputs): PythonProgram {
  return {
    source: input.programSource, parameters: parseProgramParameters(input.programParameters),
    data_requirements: { field_ids: parseProgramFields(input.programFields), history_sessions: Number(input.programHistorySessions) },
  };
}

export function programDraft(program: PythonProgram): ProgramInputs {
  return {
    programSource: program.source, programParameters: JSON.stringify(program.parameters),
    programFields: program.data_requirements.field_ids.join("\n"), programHistorySessions: String(program.data_requirements.history_sessions),
  };
}

export function programInputIssues(input: ProgramInputs): { field: ProgramInputField; code: "programSource" | "programParameters" | "programFields" | "programHistory" }[] {
  const issues: { field: ProgramInputField; code: "programSource" | "programParameters" | "programFields" | "programHistory" }[] = [];
  if (!input.programSource.trim() || new TextEncoder().encode(input.programSource).byteLength > 65536) {
    issues.push({ field: "programSource", code: "programSource" });
  }
  try {
    const parameters = parseProgramParameters(input.programParameters);
    if (new TextEncoder().encode(JSON.stringify(parameters)).byteLength > 65536) throw new Error();
  } catch { issues.push({ field: "programParameters", code: "programParameters" }); }
  const fields = parseProgramFields(input.programFields);
  if (fields.length > 32 || new Set(fields).size !== fields.length || fields.some(field => field.length > 200)) {
    issues.push({ field: "programFields", code: "programFields" });
  }
  const history = Number(input.programHistorySessions);
  if (!Number.isInteger(history) || history < 1 || history > 253) {
    issues.push({ field: "programHistorySessions", code: "programHistory" });
  }
  return issues;
}

export const DIRECT_EXAMPLE = `def decide(context, state, parameters):
    history = context["history"]
    prices = history["fields"]["price.close.adjusted"]
    candidates = {row["instrument_id"] for row in context["candidates"]}
    scores = {}
    for instrument, closes in zip(history["instruments"], prices):
        if closes[0] is not None and closes[-1] is not None and closes[0] > 0:
            scores[instrument] = closes[-1] / closes[0] - 1
    eligible = [item for item in scores if item in candidates]
    output = None
    if eligible:
        best = max(eligible, key=lambda item: (scores[item], item))
        held = [row["instrument_id"] for row in context["account"]["positions"]]
        held_score = max((scores.get(item, -1) for item in held), default=-1)
        if best not in held and (not held or scores[best] > held_score + parameters["improvement"]):
            output = {
                "reason": "better_momentum_candidate",
                "allocation": {"mode": "rebalance", "instrument_ids": [best],
                               "relative_weights": {best: "1"}, "exposure": 1.0},
                "position_limits": {},
            }
    state["decisions"] = state.get("decisions", 0) + 1
    return {"output": output, "state": state}
`;

export function parseProgramParameters(source: string): Record<string, JsonValue> {
  const value: unknown = JSON.parse(source);
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Parameters must be a JSON object.");
  }
  validateProgramJson(value);
  return value as Record<string, JsonValue>;
}

function validateProgramJson(value: unknown, depth = 0): void {
  if (depth > 32) throw new Error("Program JSON nesting exceeds 32 levels.");
  if (typeof value === "number") {
    if (!Number.isFinite(value) || (Number.isInteger(value) && !Number.isSafeInteger(value))) {
      throw new Error("Program JSON numbers must be finite; integers must be within ±(2^53−1).");
    }
  } else if (typeof value === "string") {
    // JSON.parse allows lone UTF-16 surrogates, which cannot be encoded as UTF-8.
    if (/[\uD800-\uDFFF]/u.test(value)) throw new Error("Program JSON strings must be valid Unicode.");
  } else if (Array.isArray(value)) {
    value.forEach(item => validateProgramJson(item, depth + 1));
  } else if (value !== null && typeof value === "object") {
    Object.entries(value).forEach(([key, item]) => {
      if (/[\uD800-\uDFFF]/u.test(key)) throw new Error("Program JSON keys must be valid Unicode.");
      validateProgramJson(item, depth + 1);
    });
  }
}

export function parseProgramFields(source: string): string[] {
  return source.split(/[\s,]+/).filter(Boolean);
}
