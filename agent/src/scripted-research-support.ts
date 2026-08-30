import type { LanguageModelV3CallOptions } from "@ai-sdk/provider";

export type JsonRecord = Record<string, unknown>;
export type ToolObservation = Readonly<{
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

export function latestUserText(
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

export function textContent(content: unknown): string {
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

export function toolObservations(
  options: LanguageModelV3CallOptions,
  afterIndex: number,
): readonly ToolObservation[] {
  const calls = toolCalls(options, afterIndex);
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

export function latestSuccessfulOutput(
  observations: readonly ToolObservation[],
  name: string,
): JsonRecord | undefined {
  return [...observations].reverse().find(
    (observation) => observation.name === name
      && typeof observation.output.code !== "string",
  )?.output;
}

export function latestUnresolvedTransportFailure(
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

export function requiredTool(
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

export function boundedWindowStart(coverageStart: string, coverageEnd: string): string | null {
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

export function preferredEnum(
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

export function boundedConstraintDefault(
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

export function effectRequestId(
  options: LanguageModelV3CallOptions,
  operation: string,
  revision: number,
): string | null {
  for (const message of options.prompt) {
    if (message.role !== "system") continue;
    const match = textContent(message.content).match(/Agent Run identity: ([0-9a-f-]{36})\./);
    if (match?.[1] !== undefined) {
      return `agent_${match[1].replaceAll("-", "")}_${operation}_v${revision}`;
    }
  }
  return null;
}

export function readRetryAfter(output: JsonRecord): number | undefined {
  const value = output.retry_after_seconds;
  return typeof value === "number" && Number.isInteger(value) && value >= 1 && value <= 60
    ? value
    : undefined;
}

export function factorSurfaceMetrics(result: JsonRecord): readonly JsonRecord[] | null {
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
    { label: "5-session Rank IC", value: formatMetric(rankIc.mean) },
    { label: "5-session top-bottom return", value: formatPercent(summary.top_bottom_return) },
  ];
}

export function strategySurfaceMetrics(result: JsonRecord): readonly JsonRecord[] | null {
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
    { label: "Sharpe", value: formatMetric(metrics.sharpe) },
    { label: "Net cumulative return", value: formatPercent(metrics.net_cumulative_return) },
    { label: "Maximum drawdown", value: formatPercent(drawdown.value) },
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
  return JSON.stringify(value, (_key, item: unknown) => isRecord(item)
    ? Object.fromEntries(Object.entries(item).sort(([left], [right]) => left.localeCompare(right)))
    : item);
}

export function isRecord(value: unknown): value is JsonRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
