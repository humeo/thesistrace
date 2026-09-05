import type { LanguageModelV3CallOptions } from "@ai-sdk/provider";

import {
  projectResearchA2UIContent,
  RESEARCH_A2UI_CATALOG_ID,
  RESEARCH_A2UI_PROTOCOL_VERSION,
} from "../../contracts/research-a2ui.mjs";
import {
  effectRequestId, isRecord, latestUnresolvedTransportFailure, latestUserText,
  readRetryAfter, requiredTool, strategySurfaceMetrics, textContent, toolObservations,
  type JsonRecord, type ScriptedResearchDecision, type ToolObservation,
} from "./scripted-research-support.js";

export const SCRIPTED_START_DAILY_TRACK_PROMPT = "Start daily tracking for the successful Strategy in this Chat.";
export const SCRIPTED_RELOAD_DAILY_TRACK_PROMPT = "Reload the DailyTrack view in this Chat and explain its current observations.";
export const SCRIPTED_REFRESH_DAILY_TRACK_PROMPT = "Refresh the active DailyTrack in this Chat if it is eligible.";
const SCRIPTED_RETRY_DAILY_TRACK_PROMPT = "Retry the blocked DailyTrack in this Chat if it is eligible.";
export const SCRIPTED_RESUME_DAILY_TRACK_PROMPT = "Resume DailyTrack from this Chat using the same MCP command.";
export const SCRIPTED_LIST_DAILY_TRACKS_PROMPT = "List my recent DailyTracks.";
export const SCRIPTED_STOP_DAILY_TRACK_PROMPT = "Stop the DailyTrack in this Chat.";

const TRACK_ID = /^track_[a-f0-9]{20}$/;
const RUN_ID = /^run_[a-f0-9]{20}$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const MAX_POLLS = 3;
const MAX_PAGES = 3;
type Intent = Readonly<{ kind: "start" | "reload" | "refresh" | "retry"; id?: string }>;

// Deterministic model fixture only. Real models, not the production Host, own
// these decisions using current Discovery and authoritative Tool results.
export function scriptedDailyTrackDecision(options: LanguageModelV3CallOptions): ScriptedResearchDecision | null {
  const latest = latestUserText(options);
  if (latest === undefined) return null;
  const all = toolObservations(options, -1);
  const current = all.filter((item) => item.promptIndex > latest.index);
  if (latest.text === SCRIPTED_STOP_DAILY_TRACK_PROMPT) {
    return text("The built-in Agent grant does not include tracking:stop. I cannot stop this DailyTrack; no product state was changed.");
  }
  const resume = latest.text === SCRIPTED_RESUME_DAILY_TRACK_PROMPT;
  const original = resume ? previousIntent(options, latest.index) : { index: latest.index, intent: intentFor(latest.text) };
  if (latest.text !== SCRIPTED_LIST_DAILY_TRACKS_PROMPT && !resume && original?.intent === null) return null;
  if (resume && original === null) return text("This Chat has no DailyTrack action to resume. Specify a DailyTrack or a successful Strategy ResearchRun.");
  const operation = all.filter((item) => item.promptIndex > (original?.index ?? latest.index));
  if (resume) {
    const unresolved = latestUnresolvedTransportFailure(operation);
    if (unresolved !== undefined) return requiredTool(options, unresolved.name, unresolved.input);
  }
  const failure = failureDecision(options, current);
  if (failure !== null) return failure;
  if (latest.text === SCRIPTED_LIST_DAILY_TRACKS_PROMPT) {
    const page = [...current].reverse().find((item) => item.name === "list_daily_tracks");
    if (page === undefined) return requiredTool(options, "list_daily_tracks", { limit: 20 });
    if (!validList(page.output)) return incomplete();
    return text(page.output.items.length === 0 ? "No DailyTracks are available in this Researcher account."
      : page.output.items.map((item) => `${item.id}: ${item.status} — Origin ${item.seed_run_id}`).join("\n")
        + (page.output.next_cursor === null ? "" : "\nMore DailyTracks remain; this is one bounded recent page."));
  }
  const intent = original?.intent;
  if (intent === null || intent === undefined) return incomplete();
  const target = intent.kind === "start"
    ? startTarget(options, intent, all, operation)
    : intent.id ?? latestTrackId(all);
  if (typeof target !== "string") return target ?? text("Which DailyTrack should I inspect? Specify its Track ID.");
  if (!TRACK_ID.test(target)) return incomplete();

  const acceptedRetry = operation.find((item) => item.name === "retry_daily_track"
    && item.input.track_id === target && item.output.outcome === "accepted");
  const acceptedRefresh = operation.find((item) => item.name === "refresh_daily_track"
    && item.input.track_id === target && item.output.outcome === "accepted");
  const acceptedAction = acceptedRetry ?? acceptedRefresh;
  const polls = current.filter((item) => item.name === "get_daily_track" && item.input.track_id === target
    && (acceptedAction === undefined || item.promptIndex > acceptedAction.promptIndex));
  const poll = polls.at(-1);
  if (poll === undefined) {
    const accepted = acceptedAction ?? operation.find((item) => item.name === "start_daily_track" && item.output.track_id === target);
    return requiredTool(options, "get_daily_track", { track_id: target }, accepted === undefined ? undefined : readRetryAfter(accepted.output));
  }
  const detail = poll.output;
  if (!validDetail(detail, target)) return incomplete();
  if (intent.kind === "refresh" && acceptedRefresh === undefined && detail.status === "active"
    && detail.action_eligibility.refresh === true) {
    const requestId = effectRequestId(options, "track_refresh", 1);
    return requestId === null ? incomplete() : requiredTool(options, "refresh_daily_track", { track_id: target, request_id: requestId });
  }
  if (intent.kind === "retry" && acceptedRetry === undefined && detail.status === "blocked" && detail.action_eligibility.retry === true) {
    const requestId = effectRequestId(options, "track_retry", 1);
    return requestId === null ? incomplete() : requiredTool(options, "retry_daily_track", { track_id: target, request_id: requestId });
  }
  const progressing = detail.status === "active"
    && !["up_to_date", "waiting"].includes(detail.progress.phase);
  if (progressing && polls.length < MAX_POLLS) {
    const wait = readRetryAfter(detail);
    if (wait !== undefined) return requiredTool(options, "get_daily_track", { track_id: target }, wait);
  }
  const ineligibleAction = intent.kind === "refresh" && acceptedRefresh === undefined ? "Refresh"
    : intent.kind === "retry" && acceptedRetry === undefined ? "Retry" : null;
  return currentResult(options, detail, current, poll, ineligibleAction);
}

function startTarget(
  options: LanguageModelV3CallOptions, intent: Intent,
  all: readonly ToolObservation[], operation: readonly ToolObservation[],
): string | ScriptedResearchDecision {
  const accepted = operation.find((item) => item.name === "start_daily_track" && item.output.outcome === "accepted");
  if (accepted !== undefined) return typeof accepted.output.track_id === "string" ? accepted.output.track_id : incomplete();
  const runId = intent.id ?? [...all].reverse().find((item) => item.name === "get_research_run"
    && item.output.status === "succeeded" && isRecord(item.output.input)
    && item.output.input.research_kind === "strategy_backtest")?.output.id;
  if (typeof runId !== "string" || !RUN_ID.test(runId)) return text("Specify a successful Strategy ResearchRun to use as the fixed Tracking Origin.");
  const origin = [...operation].reverse().find((item) => item.name === "get_research_run" && item.input.run_id === runId);
  if (origin === undefined) return requiredTool(options, "get_research_run", { run_id: runId });
  if (origin.output.id !== runId || origin.output.status !== "succeeded" || !isRecord(origin.output.input)
    || origin.output.input.research_kind !== "strategy_backtest") return text("DailyTrack requires a succeeded Strategy Backtest. I did not start tracking from this Origin.");
  const pages = operation.filter((item) => item.name === "list_daily_tracks" && typeof item.output.code !== "string");
  const last = pages.at(-1);
  if (last === undefined) return requiredTool(options, "list_daily_tracks", { limit: 20 });
  for (const page of pages) {
    if (!validList(page.output)) return incomplete();
    const existing = page.output.items.find((item) => item.seed_run_id === runId);
    if (existing !== undefined) return existing.id;
  }
  if (typeof last.output.next_cursor === "string") {
    if (pages.length >= MAX_PAGES || pages.some((page) => page.input.cursor === last.output.next_cursor)) {
      return text("More DailyTracks remain or the cursor repeated. I stopped the bounded lookup without creating a duplicate Origin.");
    }
    return requiredTool(options, "list_daily_tracks", { ...last.input, cursor: last.output.next_cursor });
  }
  const requestId = effectRequestId(options, "track_start", 1);
  return requestId === null ? incomplete() : requiredTool(options, "start_daily_track", { run_id: runId, request_id: requestId });
}

type TrackDetail = JsonRecord & {
  id: string; status: string; blocked_reason: string | null;
  origin: { research_run_id: string; origin_session: string };
  progress: { head_session: string; data_through_session: string; phase: string; lag_sessions: number };
  action_eligibility: { refresh: boolean; retry: boolean };
  available_result_sections: string[];
};

function currentResult(
  options: LanguageModelV3CallOptions, detail: TrackDetail,
  current: readonly ToolObservation[], poll: ToolObservation,
  ineligibleAction: "Refresh" | "Retry" | null,
): ScriptedResearchDecision {
  const requiredSections = ["strategy_summary", "strategy_observations", "provenance"];
  if (!requiredSections.every((section) => detail.available_result_sections.includes(section))) return incomplete();
  const results = current.filter((item) => item.name === "get_daily_track_result" && item.input.track_id === detail.id
    && typeof item.output.code !== "string");
  for (const section of requiredSections) {
    if (!results.some((item) => item.input.section === section)) {
      return requiredTool(options, "get_daily_track_result", {
        track_id: detail.id, section, ...(section === "strategy_observations" ? { limit: 50 } : {}),
      });
    }
  }
  if (results.some((item) => item.output.track_id !== detail.id || item.output.section !== item.input.section)) return incomplete();
  const summary = results.find((item) => item.input.section === "strategy_summary")!.output;
  const provenance = results.find((item) => item.input.section === "provenance")!.output;
  const pages = results.filter((item) => item.input.section === "strategy_observations");
  const last = pages.at(-1)!;
  if (pages.some((page) => !Array.isArray(page.output.items)
    || (page.output.next_cursor !== null && typeof page.output.next_cursor !== "string"))) return incomplete();
  if (typeof last.output.next_cursor === "string" && pages.length < MAX_PAGES) {
    if (pages.some((page) => page.input.cursor === last.output.next_cursor)) return text("The Observation cursor repeated; I stopped without claiming the latest Observation.");
    return requiredTool(options, "get_daily_track_result", { ...last.input, cursor: last.output.next_cursor });
  }
  const observations = pages.flatMap((page) => page.output.items as unknown[]);
  if (observations.some((item) => !validObservation(item))) return incomplete();
  const latest = observations.at(-1) as JsonRecord | undefined;
  const complete = last.output.next_cursor === null;
  const metrics = strategySurfaceMetrics({ metrics: summary.summary });
  if (metrics === null || !isRecord(provenance.frozen_research_input)
    || typeof provenance.frozen_research_input.formula !== "string"
    || provenance.origin_research_run_id !== detail.origin.research_run_id
    || summary.strategy_session !== detail.progress.head_session
    || provenance.tracking_strategy_session !== summary.strategy_session
    || (complete && latest?.session !== summary.strategy_session)) return incomplete();
  const surfaceId = `daily-track-${poll.toolCallId}`;
  const note = `DailyTrack ${detail.id} is ${detail.status} (${detail.progress.phase}). The current view can advance; it is not a new immutable Research Result. Core Tracking Worker continues independently of this Chat.`
    + (ineligibleAction === null ? "" : ` The current lifecycle is not eligible for ${ineligibleAction}; no ${ineligibleAction} was submitted.`)
    + (complete ? "" : " More Observation pages remain; the displayed row is only the latest retrieved, not the current latest Observation.");
  if (current.some((item) => item.name === "render_a2ui" && item.input.surfaceId === surfaceId)) return text(note);
  const components = [
    { component: "Column", id: "root", gap: "normal", children: ["title", "state", "dates", "block", "metrics", "observation", "provenance", "navigation"] },
    { component: "Text", id: "title", variant: "title", text: `DailyTrack ${detail.id}` },
    { component: "Text", id: "state", text: `Status ${detail.status} · Advance phase ${detail.progress.phase}` },
    { component: "Text", id: "dates", text: `Origin ${detail.origin.research_run_id} · Tracking session ${detail.progress.head_session} · Data through ${detail.progress.data_through_session}` },
    { component: "Text", id: "block", text: detail.blocked_reason ?? "No block reason." },
    { component: "ResultMetrics", id: "metrics", title: "Current DailyTrack metrics", metrics },
    { component: "Table", id: "observation", caption: complete ? "Latest DailyTrack Observation" : "Latest retrieved Observation (partial)",
      columns: ["Session", "Net NAV", "Net cash (CNY)", "Holdings", "Transaction cost (CNY)"],
      rows: latest === undefined ? [] : [[String(latest.session), String(latest.net_nav), String(latest.net_cash), String(latest.holdings_count), String(latest.transaction_cost_cny)]],
      initiallyExpanded: true, summary: "Inspect current Observation" },
    { component: "Provenance", id: "provenance", summary: "Inspect DailyTrack provenance", entries: [
      { label: "Origin ResearchRun", value: detail.origin.research_run_id },
      { label: "Origin session", value: detail.origin.origin_session },
      { label: "Formula", value: provenance.frozen_research_input.formula },
      { label: "Current view", value: note },
    ] },
    { component: "Navigation", id: "navigation", href: `/daily-tracks/${detail.id}`, label: "Open DailyTrack" },
  ];
  const projection = projectResearchA2UIContent({ a2ui_operations: [
    { version: RESEARCH_A2UI_PROTOCOL_VERSION, createSurface: { catalogId: RESEARCH_A2UI_CATALOG_ID, surfaceId } },
    { version: RESEARCH_A2UI_PROTOCOL_VERSION, updateComponents: { components, surfaceId } },
  ] });
  return projection.valid && projection.kind === "ready"
    ? requiredTool(options, "render_a2ui", { components, surfaceId, data: {} }) : incomplete();
}

function validDetail(value: JsonRecord, id: string): value is TrackDetail {
  return value.id === id && ["active", "blocked", "stopping", "stopped"].includes(String(value.status))
    && isRecord(value.origin) && typeof value.origin.research_run_id === "string" && RUN_ID.test(value.origin.research_run_id)
    && typeof value.origin.origin_session === "string" && DATE.test(value.origin.origin_session)
    && isRecord(value.progress) && typeof value.progress.head_session === "string" && DATE.test(value.progress.head_session)
    && typeof value.progress.data_through_session === "string" && DATE.test(value.progress.data_through_session)
    && typeof value.progress.phase === "string" && ["waiting", "queued", "retry_wait", "starting", "calculating", "result_ready", "staging", "stopping", "blocked", "up_to_date", "stopped"].includes(value.progress.phase)
    && isRecord(value.action_eligibility) && typeof value.action_eligibility.refresh === "boolean"
    && typeof value.action_eligibility.retry === "boolean"
    && (value.blocked_reason === null || typeof value.blocked_reason === "string")
    && Array.isArray(value.available_result_sections);
}

function validList(value: JsonRecord): value is JsonRecord & { items: { id: string; seed_run_id: string; status: string }[] } {
  return Array.isArray(value.items) && value.items.every((item) => isRecord(item)
    && typeof item.id === "string" && TRACK_ID.test(item.id)
    && typeof item.seed_run_id === "string" && RUN_ID.test(item.seed_run_id)
    && ["active", "blocked", "stopping", "stopped"].includes(String(item.status)))
    && (value.next_cursor === null || typeof value.next_cursor === "string");
}

function validObservation(value: unknown): value is JsonRecord {
  return isRecord(value) && typeof value.session === "string" && DATE.test(value.session)
    && Number.isSafeInteger(value.holdings_count) && Number(value.holdings_count) >= 0
    && ["net_nav", "net_cash", "transaction_cost_cny"].every((key) => typeof value[key] === "string"
      && /^[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$/.test(value[key]) && Number.isFinite(Number(value[key])));
}

function latestTrackId(observations: readonly ToolObservation[]): string | undefined {
  for (const observation of [...observations].reverse()) {
    const id = observation.name === "get_daily_track" ? observation.output.id
      : ["start_daily_track", "refresh_daily_track", "retry_daily_track"].includes(observation.name)
        ? observation.output.track_id : undefined;
    if (typeof id === "string" && TRACK_ID.test(id)) return id;
  }
  return undefined;
}

function intentFor(prompt: string): Intent | null {
  if (prompt === SCRIPTED_START_DAILY_TRACK_PROMPT) return { kind: "start" };
  if (prompt === SCRIPTED_RELOAD_DAILY_TRACK_PROMPT) return { kind: "reload" };
  if (prompt === SCRIPTED_REFRESH_DAILY_TRACK_PROMPT) return { kind: "refresh" };
  if (prompt === SCRIPTED_RETRY_DAILY_TRACK_PROMPT) return { kind: "retry" };
  const start = /^Start daily tracking for (run_[a-f0-9]{20})\.$/.exec(prompt);
  if (start?.[1] !== undefined) return { kind: "start", id: start[1] };
  const track = /^(Reload|Refresh|Retry blocked) DailyTrack (track_[a-f0-9]{20})\.$/.exec(prompt);
  const kind = track?.[1] === "Reload" ? "reload" : track?.[1] === "Refresh" ? "refresh" : "retry";
  return track?.[2] === undefined ? null : { kind, id: track[2] };
}

function previousIntent(options: LanguageModelV3CallOptions, before: number): { index: number; intent: Intent } | null {
  for (let index = before - 1; index >= 0; index -= 1) {
    const message = options.prompt[index];
    if (message?.role !== "user") continue;
    const intent = intentFor(textContent(message.content));
    if (intent !== null) return { index, intent };
  }
  return null;
}

function failureDecision(options: LanguageModelV3CallOptions, current: readonly ToolObservation[]): ScriptedResearchDecision | null {
  const last = current.at(-1);
  if (typeof last?.output.code !== "string") return null;
  const attempts = current.filter((item) => item.name === last.name && typeof item.output.code === "string").length;
  const wait = readRetryAfter(last.output);
  return last.output.code === "TEMPORARILY_UNAVAILABLE" && wait !== undefined && attempts < 3
    ? requiredTool(options, last.name, last.input, wait)
    : text(`The DailyTrack Tool reported ${last.output.code}. I stopped without repeating an uncertain effect, changing Track lifecycle, or inventing current results.`);
}

function text(value: string): ScriptedResearchDecision { return { kind: "text", text: value }; }
function incomplete(): ScriptedResearchDecision {
  return text("The current DailyTrack result is incomplete, changed during these reads, or exceeds display limits. Reload authoritative state before making another claim.");
}
