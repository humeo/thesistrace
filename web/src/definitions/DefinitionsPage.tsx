import { useCallback, useEffect, useRef, useState } from "react";

type DefinitionSummary = { id: string; name: string; revision: number };
type DefinitionList = { items: DefinitionSummary[]; next_cursor: string | null };
type DefinitionDetail = DefinitionSummary & {
  hypothesis: string | null;
  alpha: Record<string, unknown> | null;
  universe: "top300" | "top1000" | "top2000" | "top3000" | null;
  neutralization: "none" | "industry" | null;
  holdings_count: number | null;
  rebalance_every_sessions: number | null;
};
type IntegerBounds = { minimum: number; maximum: number };
type AuthorableField = {
  field_id: string;
  definition: string;
  unit: string;
  result_type: "numeric";
};
type OperandRule = "numeric" | "window";
type Operator = {
  operator_id: string;
  kind: "arithmetic" | "scalar" | "historical" | "rolling";
  arity: number;
  operand_rules: OperandRule[];
  result_type: "numeric";
  rolling_bounds: IntegerBounds | null;
};
type AuthoringOptions = {
  fields: AuthorableField[];
  operators: Operator[];
  universes: DefinitionDetail["universe"][];
  neutralizations: DefinitionDetail["neutralization"][];
  holdings_count: IntegerBounds;
  rebalance_every_sessions: IntegerBounds;
};
type AlphaEditor = { operatorId: string; operandValues: string[] };
type ErrorKind = "load" | "save" | "conflict";

export function DefinitionsPage({ definitionId }: { definitionId?: string }) {
  const [activeDefinitionId, setActiveDefinitionId] = useState(definitionId);
  const [items, setItems] = useState<DefinitionSummary[] | null>(null);
  const [options, setOptions] = useState<AuthoringOptions | null>(null);
  const [definition, setDefinition] = useState<DefinitionDetail | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [hypothesis, setHypothesis] = useState("");
  const [alpha, setAlpha] = useState<Record<string, unknown> | null>(null);
  const [alphaEditor, setAlphaEditor] = useState<AlphaEditor | null>(null);
  const [universe, setUniverse] = useState("");
  const [neutralization, setNeutralization] = useState("");
  const [holdingsCount, setHoldingsCount] = useState("");
  const [rebalanceInterval, setRebalanceInterval] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorKind, setErrorKind] = useState<ErrorKind | null>(null);
  const [busy, setBusy] = useState<"loading" | "refreshing" | "saving" | null>(
    "loading",
  );
  const busyRef = useRef(false);
  const loadController = useRef<AbortController | null>(null);
  const loadGeneration = useRef(0);
  const skipNextRouteLoad = useRef(false);

  const applyDefinition = useCallback((loaded: DefinitionDetail, catalog: AuthoringOptions) => {
    setDefinition(loaded);
    setName(loaded.name);
    setHypothesis(loaded.hypothesis ?? "");
    setAlpha(loaded.alpha);
    setAlphaEditor(readAlphaEditor(loaded.alpha, catalog));
    setUniverse(loaded.universe ?? "");
    setNeutralization(loaded.neutralization ?? "");
    setHoldingsCount(toInputValue(loaded.holdings_count));
    setRebalanceInterval(toInputValue(loaded.rebalance_every_sessions));
    setCreating(false);
  }, []);

  const load = useCallback(async (
    kind: "loading" | "refreshing" = "loading",
    supersede = false,
  ) => {
    if (busyRef.current && !supersede) return;
    loadController.current?.abort();
    const controller = new AbortController();
    loadController.current = controller;
    const generation = ++loadGeneration.current;
    busyRef.current = true;
    setBusy(kind);
    setError(null);
    setErrorKind(null);
    setStatus(null);
    try {
      const optionsRequest = fetch("/api/definitions/authoring-options", {
        signal: controller.signal,
      });
      if (activeDefinitionId) {
        const [response, optionsResponse] = await Promise.all([
          fetch(`/api/definitions/${activeDefinitionId}`, { signal: controller.signal }),
          optionsRequest,
        ]);
        if (!response.ok || !optionsResponse.ok) {
          throw new Error("Research Definition unavailable");
        }
        const loaded = (await response.json()) as DefinitionDetail;
        const catalog = (await optionsResponse.json()) as AuthoringOptions;
        if (generation !== loadGeneration.current) return;
        setOptions(catalog);
        applyDefinition(loaded, catalog);
      } else {
        const [response, optionsResponse] = await Promise.all([
          fetch("/api/definitions", { signal: controller.signal }),
          optionsRequest,
        ]);
        if (!response.ok || !optionsResponse.ok) {
          throw new Error("Research Definitions unavailable");
        }
        const loaded = (await response.json()) as DefinitionList;
        const catalog = (await optionsResponse.json()) as AuthoringOptions;
        if (generation !== loadGeneration.current) return;
        setItems(loaded.items);
        setOptions(catalog);
      }
      if (kind === "refreshing") setStatus("Refreshed.");
    } catch (reason: unknown) {
      if (
        generation !== loadGeneration.current ||
        (reason instanceof DOMException && reason.name === "AbortError")
      ) return;
      setStatus(null);
      setErrorKind("load");
      setError(
        activeDefinitionId
          ? "Research Definition unavailable"
          : "Research Definitions unavailable",
      );
    } finally {
      if (generation === loadGeneration.current) {
        busyRef.current = false;
        setBusy(null);
      }
    }
  }, [activeDefinitionId, applyDefinition]);

  useEffect(() => {
    if (skipNextRouteLoad.current) {
      skipNextRouteLoad.current = false;
    } else {
      void load("loading", true);
    }
    return () => {
      loadGeneration.current += 1;
      loadController.current?.abort();
    };
  }, [load]);

  function startNew() {
    setCreating(true);
    setDefinition(null);
    setActiveDefinitionId(undefined);
    setName("");
    setHypothesis("");
    setAlpha(null);
    setAlphaEditor(null);
    setUniverse("");
    setNeutralization("");
    setHoldingsCount("");
    setRebalanceInterval("");
    setStatus(null);
    setError(null);
    setErrorKind(null);
  }

  function startAlpha() {
    if (!options?.operators.length || !options.fields.length) return;
    selectOperator(options.operators[0].operator_id);
  }

  function selectOperator(operatorId: string) {
    if (!options) return;
    const operator = options.operators.find((item) => item.operator_id === operatorId);
    if (!operator) return;
    const operandValues = operator.operand_rules.map((rule) =>
      rule === "numeric"
        ? options.fields[0]?.field_id ?? ""
        : String(operator.rolling_bounds?.minimum ?? ""),
    );
    const editor = { operatorId, operandValues };
    setAlphaEditor(editor);
    setAlpha(buildAlpha(editor, options));
  }

  function changeOperand(index: number, value: string) {
    if (!options || !alphaEditor) return;
    const operandValues = [...alphaEditor.operandValues];
    operandValues[index] = value;
    const editor = { ...alphaEditor, operandValues };
    setAlphaEditor(editor);
    setAlpha(buildAlpha(editor, options));
  }

  async function save() {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy("saving");
    setError(null);
    setErrorKind(null);
    setStatus("Saving…");
    const body: Record<string, unknown> = {
      hypothesis: hypothesis.trim() ? hypothesis : null,
      alpha,
      universe: universe || null,
      neutralization: neutralization || null,
      holdings_count: optionalNumber(holdingsCount),
      rebalance_every_sessions: optionalNumber(rebalanceInterval),
    };
    if (name.trim()) body.name = name;
    if (definition) body.expected_revision = definition.revision;
    let failureKind: ErrorKind = "save";
    try {
      const response = await fetch(
        definition ? `/api/definitions/${definition.id}` : "/api/definitions",
        {
          method: definition ? "PUT" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
      );
      if (response.status === 409) {
        failureKind = "conflict";
        const payload = await response.json() as {
          detail?: { current_revision?: number };
        };
        const currentRevision = payload.detail?.current_revision;
        throw new Error(
          typeof currentRevision === "number"
            ? `Definition changed elsewhere at revision ${currentRevision}. Your edits are unchanged.`
            : "Definition changed elsewhere. Your edits are unchanged.",
        );
      }
      if (response.status === 422) {
        throw new Error("Definition has structural errors. Your edits are unchanged.");
      }
      if (!response.ok) throw new Error("Research Definition was not saved");
      const saved = (await response.json()) as DefinitionDetail;
      if (!options) throw new Error("Authoring options unavailable");
      applyDefinition(saved, options);
      setStatus(`Saved revision ${saved.revision}.`);
      skipNextRouteLoad.current = true;
      setActiveDefinitionId(saved.id);
      window.history.replaceState({}, "", `/definitions/${saved.id}`);
    } catch (reason: unknown) {
      setStatus(null);
      setErrorKind(failureKind);
      setError(
        reason instanceof Error ? reason.message : "Research Definition was not saved",
      );
    } finally {
      busyRef.current = false;
      setBusy(null);
    }
  }

  if (error && !creating && definition === null && items === null) {
    return (
      <section aria-label="Definitions">
        <p role="alert">{error}</p>
        <button disabled={busy !== null} onClick={() => void load()}>Retry</button>
      </section>
    );
  }

  const editing = creating || definition !== null;
  if ((!editing && items === null) || options === null) {
    return <section aria-label="Definitions"><p>Loading Definitions…</p></section>;
  }
  const selectedOperator = options.operators.find(
    (operator) => operator.operator_id === alphaEditor?.operatorId,
  );

  return (
    <section aria-label="Definitions">
      <h1>Definitions</h1>
      {!editing ? (
        <>
          <button disabled={busy !== null} onClick={startNew}>New Definition</button>
          <button disabled={busy !== null} onClick={() => void load("refreshing")}>Refresh</button>
          {busy === "refreshing" && <p role="status">Refreshing…</p>}
          {status && busy === null && <p role="status">{status}</p>}
          {error && <><p role="alert">{error}</p>{errorKind === "load" && <button disabled={busy !== null} onClick={() => void load()}>Retry</button>}</>}
          {items?.length === 0 && <p>No Research Definitions yet.</p>}
          <ol aria-label="Research Definitions">
            {items?.map((item) => (
              <li key={item.id}>
                <a href={`/definitions/${item.id}`}>{item.name}</a>
                <span> · Revision {item.revision}</span>
              </li>
            ))}
          </ol>
        </>
      ) : (
        <form onSubmit={(event) => { event.preventDefault(); void save(); }}>
          <label>
            Definition name
            <input aria-label="Definition name" onChange={(event) => setName(event.target.value)} value={name} />
          </label>
          <label>
            Hypothesis (optional)
            <textarea aria-label="Hypothesis (optional)" onChange={(event) => setHypothesis(event.target.value)} value={hypothesis} />
          </label>

          {alphaEditor && selectedOperator ? (
            <fieldset>
              <legend>Alpha</legend>
              <label>
                Alpha operator
                <select aria-label="Alpha operator" onChange={(event) => selectOperator(event.target.value)} value={alphaEditor.operatorId}>
                  {options.operators.map((operator) => <option key={operator.operator_id} value={operator.operator_id}>{operator.operator_id} · {operator.kind}</option>)}
                </select>
              </label>
              {selectedOperator.operand_rules.map((rule, index) => rule === "numeric" ? (
                <label key={`${rule}-${index}`}>
                  Alpha field {index + 1}
                  <select aria-label={`Alpha field ${index + 1}`} onChange={(event) => changeOperand(index, event.target.value)} value={alphaEditor.operandValues[index]}>
                    {options.fields.map((field) => <option key={field.field_id} value={field.field_id}>{field.definition} · {field.unit}</option>)}
                  </select>
                </label>
              ) : (
                <label key={`${rule}-${index}`}>
                  Alpha window {index + 1}
                  <input
                    aria-label={`Alpha window ${index + 1}`}
                    max={selectedOperator.rolling_bounds?.maximum}
                    min={selectedOperator.rolling_bounds?.minimum}
                    onChange={(event) => changeOperand(index, event.target.value)}
                    type="number"
                    value={alphaEditor.operandValues[index]}
                  />
                </label>
              ))}
              <button type="button" onClick={() => { setAlpha(null); setAlphaEditor(null); }}>Remove Alpha</button>
            </fieldset>
          ) : alpha ? (
            <fieldset>
              <legend>Alpha</legend>
              <p>This saved normalized Alpha is preserved exactly.</p>
              <button type="button" onClick={() => { setAlpha(null); setAlphaEditor(null); }}>Remove Alpha</button>
            </fieldset>
          ) : (
            <button type="button" onClick={startAlpha}>Add Alpha</button>
          )}

          <label>
            Universe
            <select aria-label="Universe" onChange={(event) => setUniverse(event.target.value)} value={universe}>
              <option value="">Not selected</option>
              {options.universes.map((value) => value && <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
          <label>
            Neutralization
            <select aria-label="Neutralization" onChange={(event) => setNeutralization(event.target.value)} value={neutralization}>
              <option value="">Not selected</option>
              {options.neutralizations.map((value) => value && <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
          <label>
            Holdings count
            <input aria-label="Holdings count" min={options.holdings_count.minimum} max={options.holdings_count.maximum} onChange={(event) => setHoldingsCount(event.target.value)} type="number" value={holdingsCount} />
          </label>
          <label>
            Rebalance interval
            <input aria-label="Rebalance interval" min={options.rebalance_every_sessions.minimum} max={options.rebalance_every_sessions.maximum} onChange={(event) => setRebalanceInterval(event.target.value)} type="number" value={rebalanceInterval} />
          </label>

          {definition && <p>Revision {definition.revision}</p>}
          <button disabled={busy !== null} type="submit">Save</button>
          <button disabled={busy !== null} type="button" onClick={() => void load("refreshing")}>Refresh</button>
          {busy === "refreshing" && <p role="status">Refreshing…</p>}
          {error && (
            <>
              <p role="alert">{error}</p>
              {errorKind === "load" && (
                <button disabled={busy !== null} type="button" onClick={() => void load()}>
                  Retry
                </button>
              )}
              {errorKind === "conflict" && (
                <button
                  disabled={busy !== null}
                  type="button"
                  onClick={() => void load("refreshing")}
                >
                  Discard my edits and load server version
                </button>
              )}
            </>
          )}
          {status && busy !== "refreshing" && <p role="status">{status}</p>}
        </form>
      )}
    </section>
  );
}

function buildAlpha(editor: AlphaEditor, options: AuthoringOptions): Record<string, unknown> {
  const operator = options.operators.find((item) => item.operator_id === editor.operatorId);
  if (!operator) throw new Error("Unknown Alpha operator");
  return {
    operator_id: operator.operator_id,
    operands: operator.operand_rules.map((rule, index) => rule === "numeric"
      ? { field_id: editor.operandValues[index] }
      : { literal: Number(editor.operandValues[index]) }),
  };
}

function readAlphaEditor(
  alpha: Record<string, unknown> | null,
  options: AuthoringOptions,
): AlphaEditor | null {
  if (!alpha || typeof alpha.operator_id !== "string" || !Array.isArray(alpha.operands)) {
    return null;
  }
  const operator = options.operators.find((item) => item.operator_id === alpha.operator_id);
  if (!operator || operator.operand_rules.length !== alpha.operands.length) return null;
  const operandValues: string[] = [];
  for (const [index, rule] of operator.operand_rules.entries()) {
    const operand = alpha.operands[index];
    if (!operand || typeof operand !== "object") return null;
    if (rule === "numeric") {
      const fieldId = (operand as Record<string, unknown>).field_id;
      if (typeof fieldId !== "string" || !options.fields.some((field) => field.field_id === fieldId)) return null;
      operandValues.push(fieldId);
    } else {
      const literal = (operand as Record<string, unknown>).literal;
      if (typeof literal !== "number") return null;
      operandValues.push(String(literal));
    }
  }
  return { operatorId: operator.operator_id, operandValues };
}

function optionalNumber(value: string): number | null {
  return value === "" ? null : Number(value);
}

function toInputValue(value: number | null): string {
  return value === null ? "" : String(value);
}
