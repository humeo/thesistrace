import type { LanguageModelV3CallOptions } from "@ai-sdk/provider";

export const SCRIPTED_FACTOR_IDEA_PROMPT =
  "Evaluate a low-volatility Alpha idea as a Factor Evaluation using reliable ThesisTrace defaults.";
export const SCRIPTED_STRATEGY_IDEA_PROMPT =
  "Backtest a low-volatility Alpha strategy using reliable ThesisTrace defaults.";
export const SCRIPTED_FORMULA_REPAIR_IDEA_PROMPT =
  "Develop a low-volatility Alpha, repair any Formula issue you discover, and evaluate it.";
export const SCRIPTED_ADMISSION_REPAIR_IDEA_PROMPT =
  "Evaluate a low-volatility Alpha and correct one structured admission issue if needed.";
export const SCRIPTED_SUBMIT_ONLY_IDEA_PROMPT =
  "Submit a low-volatility Factor Evaluation and return as soon as ThesisTrace accepts it.";
export const SCRIPTED_AMBIGUOUS_IDEA_PROMPT =
  "Research it for me.";
export const SCRIPTED_RETRY_INTERRUPTED_PROMPT =
  "Retry the interrupted Research Tool call with the same request.";
export const SCRIPTED_RESUME_RESEARCH_PROMPT =
  "Resume the accepted ResearchRun from this Chat and explain its authoritative Result when available.";

const RUN_IDENTITY_PATTERN = /Agent Run identity: ([0-9a-f-]{36})\./;
const RESEARCH_RUN_ID_PATTERN = /^run_[a-f0-9]{20}$/;
const MAX_SCRIPTED_POLLS = 6;
const LOW_VOLATILITY_FORMULA = "rank(-abs(pct_change(close, 1)))";
const INVALID_LOW_VOLATILITY_FORMULA = "rank(-abs(pct_change(clsoe, 1)))";
const LOW_VOLATILITY_HYPOTHESIS =
  "Stocks with smaller recent absolute returns should exhibit more stable near-term performance.";
const CATALOG_IDENTIFIERS = ["abs", "close", "pct_change", "rank"] as const;

type JsonRecord = Record<string, unknown>;
type ToolObservation = Readonly<{
  input: JsonRecord;
  name: string;
  output: JsonRecord;
  promptIndex: number;
  toolCallId: string;
}>;

export type ScriptedResearchDecision =
  | Readonly<{
      input: JsonRecord;
      kind: "tool";
      name: string;
      waitSeconds?: number;
    }>
  | Readonly<{
      kind: "text";
      text: string;
    }>;

export function scriptedResearchDecision(
  options: LanguageModelV3CallOptions,
): ScriptedResearchDecision | null {
  const latestUser = latestUserText(options);
  if (latestUser === undefined) return null;
  if (latestUser.text === SCRIPTED_AMBIGUOUS_IDEA_PROMPT) {
    return {
      kind: "text",
      text: "Which investment signal or behavior should I investigate, and do you want factor evidence or a tradable strategy backtest?",
    };
  }

  const latestMode = ideaMode(latestUser.text);
  const retryInterrupted = latestUser.text === SCRIPTED_RETRY_INTERRUPTED_PROMPT;
  const resumeResearch = latestUser.text === SCRIPTED_RESUME_RESEARCH_PROMPT;
  if (latestMode === null && !retryInterrupted && !resumeResearch) return null;

  const originalIdea = retryInterrupted || resumeResearch
    ? latestRecognizedIdea(options, latestUser.index)
    : { index: latestUser.index, mode: latestMode };
  if (originalIdea === null || originalIdea.mode === null) {
    return {
      kind: "text",
      text: "I could not find an interrupted Research request in this Chat history.",
    };
  }

  const calls = toolCalls(options, originalIdea.index);
  const observations = toolObservations(options, originalIdea.index, calls);
  if (retryInterrupted || resumeResearch) {
    const unresolved = latestUnresolvedTransportFailure(observations);
    if (unresolved !== undefined) {
      return requiredTool(options, unresolved.name, unresolved.input);
    }
  }

  const latest = observations.at(-1);
  if (latest?.output.code === "TEMPORARILY_UNAVAILABLE") {
    const retryAfter = readRetryAfter(latest.output);
    return retryAfter === undefined
      ? permanentToolFailure(latest.output)
      : requiredTool(options, latest.name, latest.input, retryAfter);
  }
  if (
    latest !== undefined
    && typeof latest.output.code === "string"
    && latest.output.code !== "MCP_TRANSPORT_UNAVAILABLE"
  ) {
    return permanentToolFailure(latest.output);
  }

  const context = latestSuccessfulOutput(observations, "get_research_context");
  if (context === undefined) {
    return requiredTool(options, "get_research_context", {});
  }
  const catalog = latestSuccessfulOutput(observations, "get_alpha_catalog");
  if (catalog === undefined) {
    return requiredTool(options, "get_alpha_catalog", {
      identifiers: [...CATALOG_IDENTIFIERS],
    });
  }
  if (!catalogSupportsFormula(catalog)) {
    return {
      kind: "text",
      text: "The current Alpha Catalog does not expose every field and operator needed for this low-volatility idea, so I did not submit Research.",
    };
  }

  const diagnostics = observations.filter(
    (observation) => observation.name === "diagnose_alpha_formula",
  );
  const lastDiagnostics = diagnostics.at(-1);
  if (lastDiagnostics === undefined) {
    return requiredTool(options, "diagnose_alpha_formula", {
      source: originalIdea.mode === "formula-repair"
        ? INVALID_LOW_VOLATILITY_FORMULA
        : LOW_VOLATILITY_FORMULA,
    });
  }
  if (lastDiagnostics.output.valid !== true) {
    if (lastDiagnostics.input.source === LOW_VOLATILITY_FORMULA) {
      return {
        kind: "text",
        text: "The Alpha Formula remains invalid after one bounded repair, so I did not submit Research.",
      };
    }
    return requiredTool(options, "diagnose_alpha_formula", {
      source: LOW_VOLATILITY_FORMULA,
    });
  }

  const submissions = observations.filter(
    (observation) => observation.name === "submit_research_run",
  );
  const accepted = [...submissions].reverse().find(
    (observation) => observation.output.outcome === "accepted",
  );
  if (accepted === undefined) {
    const rejections = submissions.filter(
      (observation) => observation.output.outcome === "rejected",
    );
    if (rejections.length > 1) {
      return {
        kind: "text",
        text: admissionStillRejectedText(rejections.at(-1)?.output),
      };
    }
    const latestRejection = rejections.at(-1)?.output;
    const repairCalculationWarmup = latestRejection === undefined
      ? false
      : isCalculationWarmupRejection(latestRejection);
    if (latestRejection !== undefined && !repairCalculationWarmup) {
      return {
        kind: "text",
        text: admissionCannotBeCorrectedText(latestRejection),
      };
    }
    const requestId = effectRequestId(options, rejections.length + 1);
    if (requestId === null) {
      return {
        kind: "text",
        text: "This Agent Run has no validated Run identity, so I stopped before creating an effect request.",
      };
    }
    const command = researchCommand({
      context,
      mode: originalIdea.mode,
      repairCalculationWarmup,
      requestId,
    });
    if (command === null) {
      return {
        kind: "text",
        text: repairCalculationWarmup
          ? "Research admission requires Calculation Warm-up, but the current market coverage cannot produce a different Research start with preceding sessions. I stopped without resubmitting or claiming that a ResearchRun exists."
          : "The current Research Context does not provide a usable default Folder and market coverage, so I need you to clarify the intended research scope.",
      };
    }
    return requiredTool(options, "submit_research_run", command);
  }

  const runId = accepted.output.run_id;
  if (typeof runId !== "string" || !RESEARCH_RUN_ID_PATTERN.test(runId)) {
    return {
      kind: "text",
      text: "Research admission returned no safe ResearchRun identifier, so I cannot claim that a run exists.",
    };
  }
  if (originalIdea.mode === "submit-only" && !resumeResearch) {
    const status = typeof accepted.output.status === "string"
      ? accepted.output.status
      : "accepted";
    return {
      kind: "text",
      text: `ResearchRun [\`${runId}\`](/research-runs/${runId}) is **${status}**. This Agent Run is ending now; the Core Worker continues independently.`,
    };
  }
  const polls = observations.filter(
    (observation) => observation.name === "get_research_run"
      && observation.input.run_id === runId,
  );
  const currentTurnPolls = polls.filter(
    (observation) => observation.promptIndex > latestUser.index,
  );
  const lastPoll = polls.at(-1);
  if (lastPoll === undefined || currentTurnPolls.length === 0) {
    return requiredTool(
      options,
      "get_research_run",
      { run_id: runId },
      readRetryAfter(accepted.output),
    );
  }

  const status = lastPoll.output.status;
  if (status === "queued" || status === "running" || status === "cancelling") {
    const retryAfter = readRetryAfter(lastPoll.output);
    if (retryAfter !== undefined && currentTurnPolls.length < MAX_SCRIPTED_POLLS) {
      return requiredTool(options, "get_research_run", { run_id: runId }, retryAfter);
    }
    return {
      kind: "text",
      text: activeResearchText(lastPoll.output, runId),
    };
  }
  if (status === "failed" || status === "cancelled") {
    return {
      kind: "text",
      text: terminalFailureText(status, runId),
    };
  }
  if (status !== "succeeded") {
    return {
      kind: "text",
      text: `ResearchRun [\`${runId}\`](/research-runs/${runId}) returned a lifecycle status I could not interpret. I stopped without claiming success or failure and did not request a Result.`,
    };
  }

  const resultSection = originalIdea.mode === "strategy"
    ? "strategy_summary"
    : "factor";
  if (!availableSections(lastPoll.output).includes(resultSection)) {
    return {
      kind: "text",
      text: `ResearchRun [\`${runId}\`](/research-runs/${runId}) succeeded, but it did not advertise the expected ${resultSection} Result section.`,
    };
  }
  const result = [...observations].reverse().find(
    (observation) => observation.name === "get_research_run_result"
      && observation.input.run_id === runId
      && observation.input.section === resultSection,
  );
  if (result === undefined) {
    return requiredTool(options, "get_research_run_result", {
      run_id: runId,
      section: resultSection,
    });
  }

  const submittedInput = isRecord(lastPoll.output.input)
    ? lastPoll.output.input
    : null;
  if (submittedInput === null) {
    return {
      kind: "text",
      text: "The succeeded ResearchRun did not return its authoritative immutable input, so I cannot construct a Result artifact.",
    };
  }
  const artifact = researchResultMarkdown({
    input: submittedInput,
    mode: originalIdea.mode,
    result: result.output,
    runId,
  });
  return {
    kind: "text",
    text: artifact ?? "The authoritative Research Result is incomplete, so I cannot construct a Result artifact without inventing fields.",
  };
}

function ideaMode(text: string): "factor" | "strategy" | "formula-repair" | "admission-repair" | "submit-only" | null {
  switch (text) {
    case SCRIPTED_FACTOR_IDEA_PROMPT: return "factor";
    case SCRIPTED_STRATEGY_IDEA_PROMPT: return "strategy";
    case SCRIPTED_FORMULA_REPAIR_IDEA_PROMPT: return "formula-repair";
    case SCRIPTED_ADMISSION_REPAIR_IDEA_PROMPT: return "admission-repair";
    case SCRIPTED_SUBMIT_ONLY_IDEA_PROMPT: return "submit-only";
    default: return null;
  }
}

function latestRecognizedIdea(
  options: LanguageModelV3CallOptions,
  beforeIndex: number,
): Readonly<{
  index: number;
  mode: ReturnType<typeof ideaMode>;
}> | null {
  for (let index = beforeIndex - 1; index >= 0; index -= 1) {
    const message = options.prompt[index];
    if (message?.role !== "user") continue;
    const text = textContent(message.content);
    const mode = ideaMode(text);
    if (mode !== null) return { index, mode };
  }
  return null;
}

function latestUserText(
  options: LanguageModelV3CallOptions,
): Readonly<{ index: number; text: string }> | undefined {
  for (let index = options.prompt.length - 1; index >= 0; index -= 1) {
    const message = options.prompt[index];
    if (message?.role === "user") {
      return { index, text: textContent(message.content) };
    }
  }
  return undefined;
}

function textContent(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .filter((part): part is Readonly<{ text: string; type: "text" }> => (
      isRecord(part) && part.type === "text" && typeof part.text === "string"
    ))
    .map((part) => part.text)
    .join("");
}

function toolCalls(
  options: LanguageModelV3CallOptions,
  afterIndex: number,
): ReadonlyMap<string, Readonly<{
  input: JsonRecord;
  name: string;
  promptIndex: number;
}>> {
  const calls = new Map<string, Readonly<{
    input: JsonRecord;
    name: string;
    promptIndex: number;
  }>>();
  for (let promptIndex = afterIndex + 1; promptIndex < options.prompt.length; promptIndex += 1) {
    const message = options.prompt[promptIndex];
    if (message === undefined) continue;
    if (message.role !== "assistant" || !Array.isArray(message.content)) continue;
    for (const part of message.content) {
      if (
        part.type !== "tool-call"
        || typeof part.toolCallId !== "string"
        || typeof part.toolName !== "string"
        || !isRecord(part.input)
      ) continue;
      calls.set(part.toolCallId, { input: part.input, name: part.toolName, promptIndex });
    }
  }
  return calls;
}

function toolObservations(
  options: LanguageModelV3CallOptions,
  afterIndex: number,
  calls: ReadonlyMap<string, Readonly<{
    input: JsonRecord;
    name: string;
    promptIndex: number;
  }>>,
): readonly ToolObservation[] {
  const observations: ToolObservation[] = [];
  for (let promptIndex = afterIndex + 1; promptIndex < options.prompt.length; promptIndex += 1) {
    const message = options.prompt[promptIndex];
    if (message === undefined) continue;
    if (message.role !== "tool" || !Array.isArray(message.content)) continue;
    for (const part of message.content) {
      if (part.type !== "tool-result" || typeof part.toolCallId !== "string") continue;
      const call = calls.get(part.toolCallId);
      const name = typeof part.toolName === "string" ? part.toolName : call?.name;
      const output = unwrapOutput(part.output);
      if (name === undefined || call === undefined || !isRecord(output)) continue;
      observations.push({
        input: call.input,
        name,
        output,
        promptIndex,
        toolCallId: part.toolCallId,
      });
    }
  }
  return observations;
}

function unwrapOutput(value: unknown): unknown {
  if (isRecord(value) && value.type === "json" && "value" in value) {
    return unwrapOutput(value.value);
  }
  if (isRecord(value) && value.type === "text" && typeof value.value === "string") {
    try {
      const parsed: unknown = JSON.parse(value.value);
      return isRecord(parsed) ? parsed : value;
    } catch {
      return value;
    }
  }
  if (isRecord(value) && isRecord(value.structuredContent)) {
    return unwrapOutput(value.structuredContent);
  }
  if (isRecord(value) && Array.isArray(value.content)) {
    for (const part of value.content) {
      if (!isRecord(part) || part.type !== "text" || typeof part.text !== "string") {
        continue;
      }
      try {
        const parsed: unknown = JSON.parse(part.text);
        if (isRecord(parsed)) return parsed;
      } catch {
        // The structured result, when present, remains authoritative.
      }
    }
  }
  return value;
}

function latestSuccessfulOutput(
  observations: readonly ToolObservation[],
  name: string,
): JsonRecord | undefined {
  return [...observations].reverse().find(
    (observation) => observation.name === name
      && typeof observation.output.code !== "string",
  )?.output;
}

function latestUnresolvedTransportFailure(
  observations: readonly ToolObservation[],
): ToolObservation | undefined {
  for (let index = observations.length - 1; index >= 0; index -= 1) {
    const observation = observations[index];
    if (observation?.output.code !== "MCP_TRANSPORT_UNAVAILABLE") continue;
    const laterReplay = observations.slice(index + 1).some((candidate) => (
      candidate.name === observation.name
      && canonicalJson(candidate.input) === canonicalJson(observation.input)
    ));
    if (!laterReplay) return observation;
  }
  return undefined;
}

function requiredTool(
  options: LanguageModelV3CallOptions,
  name: string,
  input: JsonRecord,
  waitSeconds?: number,
): ScriptedResearchDecision {
  const available = options.tools?.some(
    (tool) => tool.type === "function" && tool.name === name,
  ) === true;
  return available
    ? {
        input,
        kind: "tool",
        name,
        ...(waitSeconds === undefined ? {} : { waitSeconds }),
      }
    : {
        kind: "text",
        text: `The authenticated MCP discovery did not provide the required ${name} capability, so I stopped without claiming or mutating Research.`,
      };
}

function researchCommand(options: Readonly<{
  context: JsonRecord;
  mode: NonNullable<ReturnType<typeof ideaMode>>;
  repairCalculationWarmup: boolean;
  requestId: string;
}>): JsonRecord | null {
  const dataOverview = isRecord(options.context.data_overview)
    ? options.context.data_overview
    : undefined;
  const coverage = isRecord(dataOverview?.market_coverage)
    ? dataOverview.market_coverage
    : undefined;
  const folders = isRecord(options.context.folders) && Array.isArray(options.context.folders.items)
    ? options.context.folders.items.filter(isRecord)
    : [];
  const folder = folders.find((candidate) => candidate.is_default === true);
  if (
    typeof folder?.id !== "string"
    || folder.id.length === 0
    || typeof coverage?.start !== "string"
    || typeof coverage.end !== "string"
  ) return null;

  const strategy = options.mode === "strategy";
  const endDate = coverage.end;
  const boundedStart = boundedWindowStart(coverage.start, endDate);
  const universe = preferredEnum(options.context, "universes", "top1000");
  const neutralization = preferredEnum(options.context, "neutralizations", "none");
  const holdingsCount = strategy
    ? boundedConstraintDefault(options.context, "holdings_count", 10)
    : null;
  const rebalanceEverySessions = strategy
    ? boundedConstraintDefault(options.context, "rebalance_every_sessions", 5)
    : null;
  if (
    boundedStart === null
    || universe === null
    || neutralization === null
    || (strategy && (holdingsCount === null || rebalanceEverySessions === null))
  ) return null;
  // Core derives Formula warmup from sessions before the Research start. When
  // the selected start is the Dataset boundary, moving it later makes the
  // already-published prefix available as warmup; Core remains authoritative
  // and revalidates the revised command. A one-session coverage cannot change.
  if (options.repairCalculationWarmup && boundedStart === endDate) return null;
  const startDate = options.repairCalculationWarmup ? endDate : boundedStart;
  return {
    request_id: options.requestId,
    folder_id: folder.id,
    name: strategy ? "Low-volatility strategy" : "Low-volatility factor",
    formula: LOW_VOLATILITY_FORMULA,
    hypothesis: LOW_VOLATILITY_HYPOTHESIS,
    start_date: startDate,
    end_date: endDate,
    universe,
    neutralization,
    research_kind: strategy ? "strategy_backtest" : "factor_evaluation",
    ...(strategy
      ? {
          holdings_count: holdingsCount,
          rebalance_every_sessions: rebalanceEverySessions,
        }
      : {}),
  };
}

function boundedWindowStart(coverageStart: string, coverageEnd: string): string | null {
  const start = strictIsoDate(coverageStart);
  const end = strictIsoDate(coverageEnd);
  if (start === null || end === null || start > end) return null;
  end.setUTCDate(end.getUTCDate() - 90);
  const candidate = end.toISOString().slice(0, 10);
  return candidate < coverageStart ? coverageStart : candidate;
}

function strictIsoDate(value: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const parsed = new Date(`${value}T00:00:00.000Z`);
  return Number.isNaN(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== value
    ? null
    : parsed;
}

function preferredEnum(
  context: JsonRecord,
  key: string,
  preferred: string,
): string | null {
  const constraints = isRecord(context.authoring_constraints)
    ? context.authoring_constraints
    : undefined;
  const values = constraints?.[key];
  if (
    !Array.isArray(values)
    || values.length === 0
    || values.some((value) => typeof value !== "string" || value.length === 0)
  ) return null;
  if (values.includes(preferred)) return preferred;
  return values[0] as string;
}

function boundedConstraintDefault(
  context: JsonRecord,
  key: string,
  preferred: number,
): number | null {
  const constraints = isRecord(context.authoring_constraints)
    ? context.authoring_constraints
    : undefined;
  const bounds = isRecord(constraints?.[key]) ? constraints[key] : undefined;
  const minimum = bounds?.minimum;
  const maximum = bounds?.maximum;
  if (
    typeof minimum !== "number"
    || typeof maximum !== "number"
    || !Number.isSafeInteger(minimum)
    || !Number.isSafeInteger(maximum)
    || minimum < 1
    || maximum < minimum
  ) return null;
  return Math.min(maximum, Math.max(minimum, preferred));
}

function effectRequestId(options: LanguageModelV3CallOptions, revision: number): string | null {
  for (const message of options.prompt) {
    if (message.role !== "system") continue;
    const match = textContent(message.content).match(RUN_IDENTITY_PATTERN);
    if (match?.[1] !== undefined) {
      return `agent_${match[1].replaceAll("-", "")}_research_v${revision}`;
    }
  }
  return null;
}

function catalogSupportsFormula(catalog: JsonRecord): boolean {
  if (!Array.isArray(catalog.unknown_identifiers)) return false;
  return catalog.unknown_identifiers.length === 0;
}

function readRetryAfter(output: JsonRecord): number | undefined {
  const value = output.retry_after_seconds;
  return typeof value === "number" && Number.isInteger(value) && value >= 1 && value <= 60
    ? value
    : undefined;
}

function availableSections(output: JsonRecord): readonly string[] {
  return Array.isArray(output.available_result_sections)
    ? output.available_result_sections.filter(
        (section): section is string => typeof section === "string",
      )
    : [];
}

function admissionStillRejectedText(output: JsonRecord | undefined): string {
  const issues = Array.isArray(output?.issues) ? output.issues.filter(isRecord) : [];
  const codes = issues
    .map((issue) => issue.code)
    .filter((code): code is string => typeof code === "string")
    .slice(0, 3);
  return codes.length === 0
    ? "Research admission remained rejected after one bounded correction, so no ResearchRun was created."
    : `Research admission remained rejected after one bounded correction (${codes.join(", ")}), so no ResearchRun was created.`;
}

function admissionCannotBeCorrectedText(output: JsonRecord): string {
  const issues = Array.isArray(output.issues) ? output.issues.filter(isRecord) : [];
  const codes = issues
    .map((issue) => issue.code)
    .filter((code): code is string => typeof code === "string")
    .slice(0, 3);
  return codes.length === 0
    ? "Research admission was rejected by a structured issue I could not safely correct, so I stopped without resubmitting or claiming that a ResearchRun exists."
    : `Research admission was rejected (${codes.join(", ")}). I could not safely derive a corrected command from that issue, so I stopped without resubmitting or claiming that a ResearchRun exists.`;
}

function isCalculationWarmupRejection(output: JsonRecord): boolean {
  if (!Array.isArray(output.issues) || output.issues.length !== 1) return false;
  const issue = output.issues[0];
  return isRecord(issue)
    && issue.code === "INSUFFICIENT_CALCULATION_WARMUP"
    && issue.field === "start_date";
}

function permanentToolFailure(output: JsonRecord): ScriptedResearchDecision {
  const code = typeof output.code === "string" ? output.code : "UNKNOWN";
  return {
    kind: "text",
    text: `The Research Tool returned ${code}. I stopped this Agent Run without retrying a permanent failure or claiming that Research changed.`,
  };
}

function activeResearchText(output: JsonRecord, runId: string): string {
  const status = typeof output.status === "string" ? output.status : "active";
  return `ResearchRun [\`${runId}\`](/research-runs/${runId}) is **${status}**. I reached the bounded polling limit; the Core Worker continues independently and a later Chat turn can inspect it.`;
}

function terminalFailureText(status: "failed" | "cancelled", runId: string): string {
  return `ResearchRun [\`${runId}\`](/research-runs/${runId}) reached **${status}**. No successful Result was advertised, so I did not invent performance metrics.`;
}

function researchResultMarkdown(options: Readonly<{
  input: JsonRecord;
  mode: NonNullable<ReturnType<typeof ideaMode>>;
  result: JsonRecord;
  runId: string;
}>): string | null {
  const formula = options.input.formula;
  const hypothesis = options.input.hypothesis;
  const strategy = options.mode === "strategy";
  const expectedKind = strategy ? "strategy_backtest" : "factor_evaluation";
  if (
    typeof formula !== "string"
    || formula.length === 0
    || typeof hypothesis !== "string"
    || hypothesis.length === 0
    || options.input.research_kind !== expectedKind
  ) return null;
  const metrics = strategy
    ? strategyMetricLines(options.result)
    : factorMetricLines(options.result);
  if (metrics === null) return null;
  return [
    "### Research completed",
    "",
    `- **Hypothesis:** ${hypothesis}`,
    `- **Formula:** \`${formula}\``,
    `- **Research type:** ${strategy ? "Strategy Backtest" : "Factor Evaluation"}`,
    "- **Status:** Succeeded",
    ...metrics,
    `- **Conclusion:** ${strategy
      ? "The Strategy Result is authoritative; inspect return, drawdown, and cost together before treating the signal as investable."
      : "The Factor Result is authoritative; compare Rank IC, spread, and coverage rather than relying on the Formula alone."}`,
    "",
    `[Open ResearchRun \`${options.runId}\`](/research-runs/${options.runId})`,
  ].join("\n");
}

function factorMetricLines(result: JsonRecord): readonly string[] | null {
  const factor = isRecord(result.factor) ? result.factor : undefined;
  const horizons = isRecord(factor?.horizons) ? factor.horizons : undefined;
  const five = isRecord(horizons?.["5"]) ? horizons["5"] : undefined;
  const summary = isRecord(five?.summary) ? five.summary : undefined;
  const rankIc = isRecord(summary?.rank_ic) ? summary.rank_ic : undefined;
  if (
    !hasFiniteNumberOrNull(rankIc, "mean")
    || !hasFiniteNumberOrNull(summary, "top_bottom_return")
  ) return null;
  return [
    `- **5-session Rank IC:** ${formatMetric(rankIc.mean)}`,
    `- **5-session top-bottom return:** ${formatPercent(summary.top_bottom_return)}`,
  ];
}

function strategyMetricLines(result: JsonRecord): readonly string[] | null {
  const metrics = isRecord(result.metrics) ? result.metrics : undefined;
  const drawdown = isRecord(metrics?.maximum_drawdown)
    ? metrics.maximum_drawdown
    : undefined;
  if (
    !hasFiniteNumberOrNull(metrics, "sharpe")
    || !hasFiniteNumberOrNull(metrics, "net_cumulative_return")
    || !hasFiniteNumberOrNull(drawdown, "value")
  ) return null;
  return [
    `- **Sharpe:** ${formatMetric(metrics?.sharpe)}`,
    `- **Net cumulative return:** ${formatPercent(metrics?.net_cumulative_return)}`,
    `- **Maximum drawdown:** ${formatPercent(drawdown?.value)}`,
  ];
}

function hasFiniteNumberOrNull(
  record: JsonRecord | undefined,
  key: string,
): record is JsonRecord & Record<string, number | null> {
  if (record === undefined || !Object.hasOwn(record, key)) return false;
  const value = record[key];
  return value === null || (typeof value === "number" && Number.isFinite(value));
}

function formatMetric(value: number | null): string {
  return value === null ? "Unavailable" : value.toFixed(4);
}

function formatPercent(value: number | null): string {
  return value === null ? "Unavailable" : `${(value * 100).toFixed(2)}%`;
}

function canonicalJson(value: JsonRecord): string {
  return JSON.stringify(Object.fromEntries(Object.entries(value).sort(([a], [b]) => (
    a.localeCompare(b)
  ))));
}

function isRecord(value: unknown): value is JsonRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
