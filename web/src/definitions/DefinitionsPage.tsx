import { useCallback, useEffect, useRef, useState } from "react";

import type { DataOverview } from "../data/DataPage";
import {
  confirmDraftReplacement,
  persistResearchDraft,
  readResearchDraft,
  type ResearchBrowserDraft,
} from "./browserDraft";

type DefinitionSummary = { id: string; name: string; revision: number };
type DefinitionList = { items: DefinitionSummary[]; next_cursor: string | null };
type DefinitionDetail = DefinitionSummary & {
  hypothesis: string | null;
  start_date: string | null;
  end_date: string | null;
  alpha: Record<string, unknown> | null;
  universe: "top300" | "top1000" | "top2000" | "top3000" | null;
  neutralization: "none" | "industry" | null;
  holdings_count: number | null;
  rebalance_every_sessions: number | null;
};

type ResearchDateFieldsProps = {
  coverageStart: string | null;
  coverageEnd: string | null;
  disabled?: boolean;
  startDate: string;
  endDate: string;
  onStartDateChange: (value: string) => void;
  onEndDateChange: (value: string) => void;
};

export function ResearchDateFields({
  coverageStart,
  coverageEnd,
  disabled = false,
  startDate,
  endDate,
  onStartDateChange,
  onEndDateChange,
}: ResearchDateFieldsProps) {
  const issue = researchDateIssue(startDate, endDate, coverageStart, coverageEnd);
  const startMaximum = earlierDate(endDate, coverageEnd);
  const endMinimum = laterDate(startDate, coverageStart);
  return (
    <fieldset>
      <legend>Research period</legend>
      <p>Both dates are required to run; incomplete drafts can still be saved.</p>
      {coverageStart && coverageEnd ? (
        <p>Available data: {coverageStart} to {coverageEnd}</p>
      ) : (
        <p>Current Data is not ready.</p>
      )}
      <label>
        Start date
        <input
          aria-label="Research start date"
          disabled={disabled}
          max={startMaximum}
          min={coverageStart ?? undefined}
          onChange={(event) => onStartDateChange(event.target.value)}
          type="date"
          value={startDate}
        />
      </label>
      <label>
        End date
        <input
          aria-label="Research end date"
          disabled={disabled}
          max={coverageEnd ?? undefined}
          min={endMinimum}
          onChange={(event) => onEndDateChange(event.target.value)}
          type="date"
          value={endDate}
        />
      </label>
      {issue && (startDate || endDate) ? <p role="alert">{issue}</p> : null}
    </fieldset>
  );
}
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
type RunValidationIssue = { code: string; field: string; message: string };
type DefinitionRunOutcome = {
  outcome: "rejected" | "accepted";
  definition: DefinitionDetail;
  issues: RunValidationIssue[];
  run: {
    id: string;
    status: "queued";
  } | null;
};

export function DefinitionsPage({ definitionId }: { definitionId?: string }) {
  const [activeDefinitionId, setActiveDefinitionId] = useState(definitionId);
  const [items, setItems] = useState<DefinitionSummary[] | null>(null);
  const [options, setOptions] = useState<AuthoringOptions | null>(null);
  const [dataOverview, setDataOverview] = useState<DataOverview | null>(null);
  const [definition, setDefinition] = useState<DefinitionDetail | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [hypothesis, setHypothesis] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [alpha, setAlpha] = useState<Record<string, unknown> | null>(null);
  const [alphaEditor, setAlphaEditor] = useState<AlphaEditor | null>(null);
  const [universe, setUniverse] = useState("");
  const [neutralization, setNeutralization] = useState("");
  const [holdingsCount, setHoldingsCount] = useState("");
  const [rebalanceInterval, setRebalanceInterval] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorKind, setErrorKind] = useState<ErrorKind | null>(null);
  const [runIssues, setRunIssues] = useState<RunValidationIssue[]>([]);
  const [busy, setBusy] = useState<
    "loading" | "refreshing" | "saving" | "running" | null
  >("loading");
  const busyRef = useRef(false);
  const loadController = useRef<AbortController | null>(null);
  const loadGeneration = useRef(0);
  const skipNextRouteLoad = useRef(false);
  const draftHydrated = useRef(false);
  const runAttempt = useRef<{ fingerprint: string; requestId: string } | null>(null);
  const coverage = dataOverview?.market_research_readiness
    ? dataOverview.market_coverage
    : null;
  const dateIssue = researchDateIssue(
    startDate,
    endDate,
    coverage?.start ?? null,
    coverage?.end ?? null,
  );

  const applyDefinition = useCallback((loaded: DefinitionDetail, catalog: AuthoringOptions) => {
    setDefinition(loaded);
    setName(loaded.name);
    setHypothesis(loaded.hypothesis ?? "");
    setStartDate(loaded.start_date ?? "");
    setEndDate(loaded.end_date ?? "");
    setAlpha(loaded.alpha);
    setAlphaEditor(readAlphaEditor(loaded.alpha, catalog));
    setUniverse(loaded.universe ?? "");
    setNeutralization(loaded.neutralization ?? "");
    setHoldingsCount(toInputValue(loaded.holdings_count));
    setRebalanceInterval(toInputValue(loaded.rebalance_every_sessions));
    setCreating(false);
  }, []);

  const applyBrowserDraft = useCallback((draft: ResearchBrowserDraft, catalog: AuthoringOptions) => {
    setDefinition(null);
    setActiveDefinitionId(undefined);
    setName(draft.name);
    setHypothesis(draft.hypothesis);
    setStartDate(draft.start_date);
    setEndDate(draft.end_date);
    setAlpha(draft.alpha);
    setAlphaEditor(readAlphaEditor(draft.alpha, catalog));
    setUniverse(draft.universe);
    setNeutralization(draft.neutralization);
    setHoldingsCount(draft.holdings_count);
    setRebalanceInterval(draft.rebalance_every_sessions);
    setCreating(true);
    draftHydrated.current = true;
  }, []);

  const load = useCallback(async (
    kind: "loading" | "refreshing" = "loading",
    supersede = false,
  ) => {
    if (busyRef.current && !supersede) return;
    draftHydrated.current = false;
    loadController.current?.abort();
    const controller = new AbortController();
    loadController.current = controller;
    const generation = ++loadGeneration.current;
    busyRef.current = true;
    setBusy(kind);
    setError(null);
    setErrorKind(null);
    setRunIssues([]);
    setStatus(null);
    try {
      const optionsRequest = fetch("/api/definitions/authoring-options", {
        signal: controller.signal,
      });
      const dataRequest = fetch("/api/data", { signal: controller.signal });
      const definitionRequest = fetch(
        activeDefinitionId
          ? `/api/definitions/${activeDefinitionId}`
          : "/api/definitions",
        { signal: controller.signal },
      );
      const [response, optionsResponse, dataResponse] = await Promise.all([
        definitionRequest,
        optionsRequest,
        dataRequest,
      ]);
      if (!response.ok || !optionsResponse.ok || !dataResponse.ok) {
        throw new Error(
          activeDefinitionId
            ? "Research Definition unavailable"
            : "Research Definitions unavailable",
        );
      }
      const catalog = (await optionsResponse.json()) as AuthoringOptions;
      const overview = (await dataResponse.json()) as DataOverview;
      if (generation !== loadGeneration.current) return;
      setOptions(catalog);
      setDataOverview(overview);
      if (activeDefinitionId) {
        const loaded = (await response.json()) as DefinitionDetail;
        if (generation !== loadGeneration.current) return;
        applyDefinition(loaded, catalog);
      } else {
        const loaded = (await response.json()) as DefinitionList;
        if (generation !== loadGeneration.current) return;
        setItems(loaded.items);
        const browserDraft = readResearchDraft(window.localStorage);
        if (browserDraft) applyBrowserDraft(browserDraft, catalog);
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
  }, [activeDefinitionId, applyBrowserDraft, applyDefinition]);

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

  useEffect(() => {
    if (!draftHydrated.current || !creating) return;
    persistResearchDraft({
      name,
      hypothesis,
      start_date: startDate,
      end_date: endDate,
      alpha,
      universe: universe as ResearchBrowserDraft["universe"],
      neutralization: neutralization as ResearchBrowserDraft["neutralization"],
      holdings_count: holdingsCount,
      rebalance_every_sessions: rebalanceInterval,
    }, window.localStorage);
  }, [
    alpha,
    creating,
    endDate,
    holdingsCount,
    hypothesis,
    name,
    neutralization,
    rebalanceInterval,
    startDate,
    universe,
  ]);

  function startNew() {
    if (!confirmDraftReplacement(
      window.localStorage,
      () => window.confirm("Replace the existing browser draft?"),
    )) return;
    setCreating(true);
    setDefinition(null);
    setActiveDefinitionId(undefined);
    setName("");
    setHypothesis("");
    setStartDate("");
    setEndDate("");
    setAlpha(null);
    setAlphaEditor(null);
    setUniverse("");
    setNeutralization("");
    setHoldingsCount("");
    setRebalanceInterval("");
    setStatus(null);
    setError(null);
    setErrorKind(null);
    setRunIssues([]);
    draftHydrated.current = true;
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
    setRunIssues([]);
    setStatus("Saving…");
    const body = currentContent();
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

  async function run() {
    if (busyRef.current || dateIssue !== null) return;
    busyRef.current = true;
    setBusy("running");
    setError(null);
    setErrorKind(null);
    setRunIssues([]);
    setStatus("Checking Run…");
    const action = {
      ...currentContent(),
      ...(definition ? { expected_revision: definition.revision } : {}),
    };
    const fingerprint = JSON.stringify({ definitionId: definition?.id ?? null, action });
    if (runAttempt.current?.fingerprint !== fingerprint) {
      runAttempt.current = { fingerprint, requestId: crypto.randomUUID() };
    }
    const body = { ...action, request_id: runAttempt.current.requestId };
    let failureKind: ErrorKind = "save";
    let terminalResponse = false;
    try {
      const response = await fetch(
        definition ? `/api/definitions/${definition.id}/run` : "/api/definitions/run",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
      );
      if (response.status === 409) {
        terminalResponse = true;
        failureKind = "conflict";
        const payload = await response.json() as {
          detail?: { current_revision?: number };
        };
        const currentRevision = payload.detail?.current_revision;
        throw new Error(
          typeof currentRevision === "number"
            ? `Definition changed elsewhere at revision ${currentRevision}. Your edits are unchanged.`
            : "Definition Run request conflicts. Your edits are unchanged.",
        );
      }
      if (response.status === 422) {
        terminalResponse = true;
        throw new Error("Definition has structural errors. Your edits are unchanged.");
      }
      if (!response.ok) throw new Error("Definition Run failed");
      const outcome = (await response.json()) as DefinitionRunOutcome;
      terminalResponse = true;
      if (!options) throw new Error("Authoring options unavailable");
      applyDefinition(outcome.definition, options);
      setRunIssues(outcome.issues);
      if (outcome.outcome === "accepted" && outcome.run) {
        runAttempt.current = null;
        window.location.assign(`/research-runs/${outcome.run.id}`);
        return;
      }
      setStatus(`Run rejected after saving revision ${outcome.definition.revision}.`);
      skipNextRouteLoad.current = true;
      setActiveDefinitionId(outcome.definition.id);
      window.history.replaceState(
        {},
        "",
        `/definitions/${outcome.definition.id}`,
      );
    } catch (reason: unknown) {
      setStatus(null);
      setErrorKind(failureKind);
      setError(
        terminalResponse && reason instanceof Error
          ? reason.message
          : "Definition Run response was not received. Run again to retry the same action.",
      );
    } finally {
      if (terminalResponse) runAttempt.current = null;
      busyRef.current = false;
      setBusy(null);
    }
  }

  function currentContent(): Record<string, unknown> {
    const content: Record<string, unknown> = {
      hypothesis: hypothesis.trim() ? hypothesis : null,
      start_date: startDate || null,
      end_date: endDate || null,
      alpha,
      universe: universe || null,
      neutralization: neutralization || null,
      holdings_count: optionalNumber(holdingsCount),
      rebalance_every_sessions: optionalNumber(rebalanceInterval),
    };
    if (name.trim()) content.name = name;
    return content;
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
  if ((!editing && items === null) || options === null || dataOverview === null) {
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
          <button disabled={busy !== null} type="button" onClick={startNew}>
            New
          </button>
          <label>
            Definition name
            <input aria-label="Definition name" onChange={(event) => setName(event.target.value)} value={name} />
          </label>
          <label>
            Hypothesis (optional)
            <textarea aria-label="Hypothesis (optional)" onChange={(event) => setHypothesis(event.target.value)} value={hypothesis} />
          </label>

          <ResearchDateFields
            coverageEnd={coverage?.end ?? null}
            coverageStart={coverage?.start ?? null}
            disabled={busy !== null}
            endDate={endDate}
            onEndDateChange={setEndDate}
            onStartDateChange={setStartDate}
            startDate={startDate}
          />

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
          <button disabled={busy !== null || dateIssue !== null} type="button" onClick={() => void run()}>
            Run
          </button>
          {(errorKind === null || errorKind === "load") && (
            <button
              disabled={busy !== null}
              type="button"
              onClick={() => void load("refreshing")}
            >
              Refresh
            </button>
          )}
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
          {runIssues.length > 0 && (
            <ul aria-label="Run validation issues">
              {runIssues.map((issue) => (
                <li key={`${issue.code}-${issue.field}`}>{issue.message}</li>
              ))}
            </ul>
          )}
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

export function researchDateIssue(
  startDate: string,
  endDate: string,
  coverageStart: string | null,
  coverageEnd: string | null,
): string | null {
  if (!coverageStart || !coverageEnd) return "Current Data is not ready";
  if (!startDate || !endDate) return "Both dates are required to run";
  if (startDate > endDate) return "Research end date must not precede start date";
  if (startDate < coverageStart || endDate > coverageEnd) {
    return "Research period must stay within current Data coverage";
  }
  return null;
}

function earlierDate(first: string, second: string | null): string | undefined {
  if (!first) return second ?? undefined;
  if (!second) return first;
  return first < second ? first : second;
}

function laterDate(first: string, second: string | null): string | undefined {
  if (!first) return second ?? undefined;
  if (!second) return first;
  return first > second ? first : second;
}
