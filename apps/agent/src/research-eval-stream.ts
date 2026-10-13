import type { BaseEvent } from "@ag-ui/core";
import { runHttpRequest, transformHttpEventStream, verifyEvents } from "@ag-ui/client";
import { concatMap, endWith, ignoreElements, lastValueFrom, tap } from "rxjs";

import { ResearchEvalError, type ResearchEvalCase } from "./research-eval.js";
import { parseSafeToolResult, type SafeToolResult } from "./safe-tool-result.js";
import type { ToolFailureCode } from "@thesistrace/contracts/agent-failure";
import { isResearchA2UIMessageId, projectResearchA2UIContent, RESEARCH_A2UI_ACTIVITY_TYPE } from "@thesistrace/contracts/research-a2ui";

export type ResearchEvalToolCall = {
  id: string; name: string; failure: ToolFailureCode | null; outcome: SafeToolResult | null;
};
export type ResearchEvalToolEvent = {
  phase: "started" | "finished"; call: ResearchEvalToolCall;
};
export type ResearchEvalTurn = {
  calls: ResearchEvalToolCall[]; toolEvents: ResearchEvalToolEvent[];
  text: string; failure: string | null; terminal: boolean;
  interrupt: Readonly<{ id: string }> | null;
};

// The isolated Eval Host has a 600-second Run ceiling. Allow 30 seconds for
// terminal delivery; a case's quality deadline must not destroy its accounting.
export const RESEARCH_EVAL_TURN_OBSERVATION_MS = 630_000;

/** One bounded request and its native AG-UI stream, without retry or reconnect. */
export async function requestResearchEvalTurn(
  request: (timeoutMs: number) => Promise<Response>,
  onToolResult: (call: ResearchEvalToolCall) => void | Promise<void> = () => undefined,
): Promise<ResearchEvalTurn> {
  return observeResearchEvalTurn(await request(RESEARCH_EVAL_TURN_OBSERVATION_MS), onToolResult);
}

/** Ephemeral observations only; generated text never crosses the report boundary. */
export async function observeResearchEvalTurn(
  response: Response,
  onToolResult: (call: ResearchEvalToolCall) => void | Promise<void> = () => undefined,
): Promise<ResearchEvalTurn> {
  const result: ResearchEvalTurn = {
    calls: [],
    failure: null,
    interrupt: null,
    terminal: false,
    text: "",
    toolEvents: [],
  };
  const surfaceText = new Map<string, string>();
  await observeResearchEvalStream(response, async (event) => {
    if (event.type === "TOOL_CALL_START") {
      const call: ResearchEvalToolCall = {
        id: String(event.toolCallId), name: String(event.toolCallName).replace(/^thesistrace_/, ""),
        failure: null, outcome: null,
      };
      result.calls.push(call);
      result.toolEvents.push({ phase: "started", call });
    }
    if (event.type === "TOOL_CALL_RESULT") {
      const call = result.calls.find((item) => item.id === event.toolCallId);
      if (call !== undefined) {
        call.outcome = parseSafeToolResult(event.content);
        if (call.outcome?.outcome === "failed") call.failure = call.outcome.failureCode ?? null;
        result.toolEvents.push({ phase: "finished", call });
        await onToolResult(call);
      }
    }
    if (event.type === "TEXT_MESSAGE_CONTENT" && typeof event.delta === "string") result.text += event.delta;
    if (event.type === "ACTIVITY_SNAPSHOT" && event.activityType === RESEARCH_A2UI_ACTIVITY_TYPE
      && isResearchA2UIMessageId(event.messageId)) {
      // Only final server-validated snapshots enter this transport. Revalidate
      // the catalog and replace this message's prior view, never count hidden
      // IDs, hrefs, layout props, partial arguments or a superseded surface.
      surfaceText.set(event.messageId, event.replace === true ? visibleA2UIText(event.content) : "");
    }
    if (event.type === "RUN_ERROR") { result.failure = String(event.code); result.terminal = true; }
    if (event.type === "RUN_FINISHED") {
      result.terminal = true;
      const outcome = event.outcome;
      const interrupt = isRecord(outcome)
        && outcome.type === "interrupt"
        && Array.isArray(outcome.interrupts)
        && outcome.interrupts.length === 1
        ? outcome.interrupts[0]
        : undefined;
      if (isRecord(interrupt) && typeof interrupt.id === "string") {
        result.interrupt = { id: interrupt.id };
      }
    }
  });
  result.text = [result.text, ...surfaceText.values()].filter(Boolean).join("\n");
  return result;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const DISPLAY_FIELDS: Readonly<Record<string, readonly string[]>> = {
  Text: ["text"], Formula: ["label", "expression"],
  AlphaProposal: ["title", "hypothesis", "universe", "period", "researchType", "strategy", "formula", "explanation"],
  Table: ["summary", "caption", "columns", "rows"],
  Navigation: ["label"],
};

function visibleA2UIText(content: unknown): string {
  const projected = projectResearchA2UIContent(content);
  if (!projected.valid || projected.kind !== "ready") return "";
  // The shared projector has checked the complete bounded literal graph.
  const operations = projected.content.a2ui_operations as Array<{ updateComponents?: { components: Array<Record<string, unknown>> } }>;
  const components = operations.flatMap((operation) => operation.updateComponents?.components ?? []);
  const byId = new Map(components.map((component) => [component.id, component]));
  const strings = (value: unknown): string[] => typeof value === "string" ? [value]
    : Array.isArray(value) ? value.flatMap(strings)
      : value !== null && typeof value === "object" ? Object.values(value).flatMap(strings) : [];
  const visit = (id: unknown): string[] => {
    const component = byId.get(id)!;
    if (component.component === "Row" || component.component === "Column") return (component.children as string[]).flatMap(visit);
    return (DISPLAY_FIELDS[String(component.component)] ?? []).flatMap((field) => strings(component[field]));
  };
  return visit("root").join("\n");
}

export function researchEvalPolledRun(events: readonly ResearchEvalToolEvent[]): boolean {
  const pending = new Set<string>();
  for (const { phase, call } of events) {
    if (phase !== "finished") continue;
    const resource = call.outcome?.resource;
    if (call.name !== "get_research_run" || call.outcome?.outcome !== "completed" || resource === undefined) continue;
    if (resource.status === "queued" || resource.status === "running") pending.add(resource.id);
    if (resource.status === "succeeded" && pending.has(resource.id)) return true;
  }
  return false;
}

/** The CLI applies identical semantic checks to prose and validated display text. */
export function researchEvalConversationMeetsOutcome(
  testCase: Pick<ResearchEvalCase, "outcome">,
  streams: readonly ResearchEvalTurn[],
  fixture: Readonly<{ runId?: string; expectedIds?: string[] }>,
): boolean {
  const text = streams.at(-1)?.text ?? "";
  if (text.trim().length < 20) return false;
  if (testCase.outcome === "ranked-strategies") return /sharpe|夏普/i.test(text);
  if (testCase.outcome === "clarified-factor") return streams.length === 2
    && /\?|？/.test(streams[0]!.text) && !streams[0]!.calls.some((call) => /^(submit_|start_|retry_)/.test(call.name));
  if (testCase.outcome === "explained-result") return fixture.runId !== undefined && text.includes(fixture.runId) && /rank.?ic/i.test(text) && /coverage/i.test(text)
    && /unavailable|insufficient|undefined|null|not .*estim|cannot|can't|too (?:few|small)|single.*stock|one.*stock/i.test(text);
  if (testCase.outcome === "polled-factor") return researchEvalPolledRun(streams.flatMap((item) => item.toolEvents));
  return true;
}

type RankingRow = Readonly<{ name: string; sharpe: number; annualized_excess_return: number;
  maximum_drawdown: number; start_date: string; end_date: string }>;

/** Check table values against the independent fixture, allowing labels and numeric formatting. */
export function researchEvalRankingTableMatches(text: string, expected: readonly RankingRow[]): boolean | null {
  const rows = text.split("\n").filter(line => line.includes("|"))
    .map(line => line.trim().replace(/^\||\|$/g, "").split("|").map(cell => cell.trim()));
  const data = rows.filter(row => expected.some(item => row.some(cell => cell.includes(item.name))));
  if (data.length === 0) return null; // An authoritative platform view can supply the display.
  const header = rows.find(row => row.some(cell => /sharpe|夏普/i.test(cell)));
  if (!header || data.length !== expected.length) return false;
  const index = (pattern: RegExp) => header.findIndex(cell => pattern.test(cell));
  const sharpe = index(/sharpe|夏普/i), excess = index(/年化.*超额|annualized.*excess/i);
  const drawdown = index(/最大.*回撤|maximum.*drawdown|max.*drawdown/i);
  const dateColumns = header.flatMap((cell, column) =>
    /区间|日期|开始|起始|结束|period|date|start|end/i.test(cell) ? [column] : []);
  const numeric = (cell: string | undefined): number | null => {
    const cleaned = cell?.replace(/[*`\s,]/g, "") ?? "";
    if (!/^[+-]?\d+(?:\.\d+)?%?$/.test(cleaned)) return null;
    return Number.parseFloat(cleaned) / (cleaned.endsWith("%") ? 100 : 1);
  };
  if ([sharpe, excess, drawdown].some(value => value < 0)) return false;
  return expected.every((item, rowIndex) => {
    const row = data[rowIndex]!;
    const dates = dateColumns.length ? dateColumns.map(column => row[column]).join(" ") : text;
    return row.some(cell => cell.includes(item.name))
      && numeric(row[sharpe]) === item.sharpe
      && numeric(row[excess]) === item.annualized_excess_return
      && numeric(row[drawdown]) === item.maximum_drawdown
      && dates.includes(item.start_date) && dates.includes(item.end_date);
  });
}

export function unresolvedResearchEvalToolFailure(events: readonly ResearchEvalToolEvent[]): ToolFailureCode | null {
  const failures = new Map<string, ToolFailureCode>();
  for (const { phase, call } of events) {
    if (phase !== "finished") continue;
    if (call.failure !== null) { failures.delete(call.name); failures.set(call.name, call.failure); }
    else if (call.outcome?.outcome === "completed") failures.delete(call.name);
  }
  return [...failures.values()].at(-1) ?? null;
}

export function researchEvalToolRetryCount(events: readonly ResearchEvalToolEvent[]): number {
  const failed = new Set<string>();
  let count = 0;
  for (const { phase, call } of events) {
    if (phase === "started") { if (failed.delete(call.name)) count++; }
    else if (call.failure !== null) failed.add(call.name);
    else if (call.outcome?.outcome === "completed") failed.delete(call.name);
  }
  return count;
}

/** Reuse the pinned AG-UI parser/verifier, without the logging Chat state reducer. */
export async function observeResearchEvalStream(
  response: Response,
  visit: (event: BaseEvent) => void | Promise<void>,
): Promise<void> {
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  try {
    if (response.status !== 200 || response.body === null
      || response.headers.get("content-type")?.split(";")[0]?.trim() !== "text/event-stream") {
      throw new ResearchEvalError("PROTOCOL_INVALID");
    }
    let bytes = 0, terminal = false, inputFailed = false, ended = false;
    reader = response.body.getReader();
    const sourceReader = reader;
    // The pinned HTTP helper rethrows a rejected reader.cancel() outside its
    // observable. Keep its reader cleanly closed, record the failure locally,
    // and reject the operation below. This is I/O cleanup, not protocol repair.
    const bounded = new ReadableStream<Uint8Array>({
      async pull(controller) {
        try {
          const part = await sourceReader.read();
          if (ended) return;
          if (part.done) { ended = true; controller.close(); return; }
          bytes += part.value.byteLength;
          if (bytes > 16 * 1024 * 1024) {
            inputFailed = true; ended = true; controller.close();
            await sourceReader.cancel().catch(() => undefined);
            return;
          }
          controller.enqueue(part.value);
        } catch {
          inputFailed = true;
          if (!ended) { ended = true; controller.close(); }
        }
      },
      async cancel() { ended = true; await sourceReader.cancel().catch(() => undefined); },
    });
    const safeResponse = new Response(bounded, { status: response.status, headers: response.headers });
    await lastValueFrom(transformHttpEventStream(runHttpRequest(async () => safeResponse), false).pipe(
      verifyEvents(false),
      tap((event) => { if (event.type === "RUN_FINISHED" || event.type === "RUN_ERROR") terminal = true; }),
      concatMap(async (event) => visit(event)),
      ignoreElements(), endWith(undefined),
    ));
    if (inputFailed || !terminal) throw new ResearchEvalError("PROTOCOL_INVALID");
  } catch {
    // Parser, callback, transport and schema errors can contain private text.
    throw new ResearchEvalError("PROTOCOL_INVALID");
  } finally {
    await reader?.cancel().catch(() => undefined);
  }
}
