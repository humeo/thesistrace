import {
  AgentRunner,
  InMemoryAgentRunner,
  type AgentRunnerConnectRequest,
  type AgentRunnerIsRunningRequest,
  type AgentRunnerRunRequest,
  type AgentRunnerStopRequest,
} from "@copilotkit/runtime/v2";
import { EventType, type BaseEvent } from "@ag-ui/core";
import {
  Observable,
  Subject,
  catchError,
  concat,
  concatMap,
  defer,
  endWith,
  filter,
  firstValueFrom,
  from,
  ignoreElements,
  mergeMap,
  of,
  shareReplay,
  tap,
} from "rxjs";

import { safeBrowserMessages } from "./browser-message-safety.js";
import { chatCommandFingerprint } from "./chat-request.js";
import { ChatTimelineProjector } from "./chat-timeline-projector.js";
import { CHAT_TIMELINE_UPDATE } from "@thesistrace/contracts/chat-events";
import { sessionResponse, timelineResponse } from "./chat-state-response.js";
import {
  SessionActiveRunError,
  type ResearchSessionRepository,
} from "./session-repository.js";
import { ResearchA2UIEventProjector } from "./research-a2ui-events.js";
import { runFailureEvent } from "./run-failure.js";
import type { RunSelection } from "@thesistrace/contracts/agent-run-selection";

export const RESEARCHER_ID_HEADER = "x-thesistrace-agent-researcher-id";
// One Host replica. Reject excess work; never create a hidden queue. Changes
// require deterministic saturation and real-model envelope qualification.
export const MAX_ACTIVE_AGENT_RUNS = 50;

type ActiveRun = Readonly<{
  events: Observable<BaseEvent>;
  fingerprint: Buffer;
  runId: string;
}>;

export class DurableResearchAgentRunner extends AgentRunner {
  private readonly delegate = new InMemoryAgentRunner({ onConcurrentRun: "throw" });
  private readonly active = new Map<string, ActiveRun>();
  private readonly sessionMutations = new Set<string>();
  private closing = false;

  constructor(private readonly repository: ResearchSessionRepository) {
    super();
  }

  run(request: AgentRunnerRunRequest): Observable<BaseEvent> {
    if (this.closing) return of(safeRunError());
    if (this.sessionMutations.has(request.threadId)) {
      return of(safeRunConflict());
    }
    const current = this.active.get(request.threadId);
    const fingerprint = chatCommandFingerprint(request.input);
    if (current?.runId === request.input.runId) {
      if (!current.fingerprint.equals(fingerprint)) {
        return of(safeRunConflict());
      }
      return current.events;
    }
    if (current !== undefined) return of(safeRunConflict());
    if (this.active.size >= MAX_ACTIVE_AGENT_RUNS) {
      return of(runFailureEvent("AGENT_CAPACITY"));
    }
    // CopilotKit forwards authenticated request headers onto its Agent clone.
    // Capture identity before ResearchMastraAgent clears provider headers.
    const researcherId = (request.agent as typeof request.agent & {
      headers?: Record<string, string>;
    }).headers?.[RESEARCHER_ID_HEADER];

    let accepted: Observable<BaseEvent>;
    try {
      accepted = this.delegate.run(request);
    } catch (error) {
      // Native Runner admission is the concurrency authority. Project its
      // rejection into AG-UI here: the framework SSE factory otherwise logs
      // the exception and closes an empty HTTP 200 response.
      return of(error instanceof Error && error.message === "Thread already running"
        ? safeRunConflict()
        : safeRunError());
    }
    const a2ui = new ResearchA2UIEventProjector();
    const timeline = new ChatTimelineProjector(
      this.repository,
      request.threadId,
      request.input.runId,
    );
    let presentationFailed = false;
    let runAccepted = false;
    let latestState: BaseEvent | null = null;
    const liveStates = new Subject<BaseEvent>();
    const source = accepted.pipe(
      concatMap((event) => defer(async () => {
        if (presentationFailed) return [];
        const revision = timeline.revision;
        await timeline.project(event);
        if (event.type === EventType.RUN_STARTED) runAccepted = true;
        const batch = a2ui.project(event);
        for (const activity of batch.activities) {
          await this.repository.persistA2UIActivity({
            ...activity,
            runId: request.input.runId,
            threadId: request.threadId,
          });
        }
        const events: BaseEvent[] = [];
        for (const projected of batch.events) {
          if (projected.type !== EventType.MESSAGES_SNAPSHOT) {
            events.push(projected);
            continue;
          }
          events.push({
            messages: [
              ...await this.repository.durableBrowserMessagesForThread(request.threadId),
            ],
            type: EventType.MESSAGES_SNAPSHOT,
          });
        }
        if (runAccepted && researcherId !== undefined && (
          timeline.revision !== revision || batch.activities.length > 0
          || event.type === EventType.RUN_STARTED || event.type === EventType.RUN_FINISHED || event.type === EventType.RUN_ERROR
          || event.type === EventType.CUSTOM && event.name === "session_recovery_changed"
        )) {
          const [session, page] = await Promise.all([
            this.repository.session(request.threadId, researcherId),
            this.repository.timeline(request.threadId, researcherId, undefined, 1),
          ]);
          const savedState: BaseEvent = { type: EventType.CUSTOM, name: CHAT_TIMELINE_UPDATE,
            value: { session: sessionResponse(session), timeline: timelineResponse({ ...page, nextCursor: null }) } };
          if (event.type === EventType.RUN_FINISHED || event.type === EventType.RUN_ERROR) events.unshift(savedState);
          else events.push(savedState);
        }
        return events;
      }).pipe(
        catchError(() => {
          // A storage/projection exception must not reach CopilotKit's raw
          // SSE error logger. Keep consuming the native Run until terminal so
          // Session deletion/concurrency cannot race still-running work.
          presentationFailed = true;
          return of([safeConnectionError()]);
        }),
        mergeMap((events) => from(events)),
      )),
      catchError(() => of(safeConnectionError())),
    );
    const nativeEvents = source.pipe(
      tap({
        next: (event) => {
          if (event.type === EventType.CUSTOM && event.name === CHAT_TIMELINE_UPDATE) {
            latestState = event;
            liveStates.next(event);
          }
        },
        complete: () => this.removeActive(request.threadId, request.input.runId),
        error: () => this.removeActive(request.threadId, request.input.runId),
      }),
      // Replaying every growing Turn snapshot would retain quadratic amounts
      // of text. Cache native deltas and only the latest persisted UI state.
      filter((event) => !(event.type === EventType.CUSTOM && event.name === CHAT_TIMELINE_UPDATE)),
      shareReplay({ bufferSize: Number.POSITIVE_INFINITY, refCount: false }),
    );
    const events = new Observable<BaseEvent>((subscriber) => {
      const states = liveStates.subscribe((event) => subscriber.next(event));
      const native = nativeEvents.subscribe({
        next: (event) => {
          subscriber.next(event);
          if (event.type === EventType.RUN_STARTED && latestState !== null) subscriber.next(latestState);
        },
        error: (error) => subscriber.error(error),
        complete: () => subscriber.complete(),
      });
      return () => { states.unsubscribe(); native.unsubscribe(); };
    });
    this.active.set(request.threadId, {
      events,
      fingerprint,
      runId: request.input.runId,
    });
    return events;
  }

  connect(request: AgentRunnerConnectRequest): Observable<BaseEvent> {
    const researcherId = request.headers?.[RESEARCHER_ID_HEADER];
    if (researcherId === undefined) {
      return of(safeConnectionError());
    }
    const captured = this.active.get(request.threadId);
    return defer(async () => {
      let snapshot = await this.repository.connectionSnapshot(request.threadId, researcherId);
      const matchingActive = () => {
        const current = this.active.get(request.threadId);
        return current?.runId === snapshot.latestRun?.id
          ? current
          : captured?.runId === snapshot.latestRun?.id ? captured : undefined;
      };
      let active = matchingActive();
      // A Run may finish while the repeatable-read snapshot is loading. Read
      // its durable terminal state once more if no captured/live stream owns
      // that snapshot; do not invent a failed model invocation.
      if (active === undefined && snapshot.latestRun?.status === "running") {
        snapshot = await this.repository.connectionSnapshot(request.threadId, researcherId);
        active = matchingActive();
      }
      return { ...snapshot, active };
    }).pipe(
      mergeMap(({ active, latestRun, messages }) => {
        const snapshot: BaseEvent = {
          type: EventType.MESSAGES_SNAPSHOT,
          messages: [...safeBrowserMessages(messages)],
        };
        if (active === undefined) {
          if (latestRun === null) return from([]);
          const started = replayRunStarted(request.threadId, latestRun.id, latestRun.selection);
          if (latestRun.status === "completed" || latestRun.status === "stopped") {
            return from([started, snapshot, replayRunFinished(request.threadId, latestRun.id)]);
          }
          if (latestRun.status === "waiting_for_user" && latestRun.question !== null) {
            return from([
              started,
              snapshot,
              replayInterruptFinished(request.threadId, latestRun.id, latestRun.question),
            ]);
          }
          return from([
            started,
            snapshot,
            runFailureEvent(latestRun.terminalErrorCode ?? "AGENT_UNAVAILABLE"),
          ]);
        }

        const persistedIds = new Set(messages.map((message) => message.id));
        let currentRunStarted = false;
        const live = active.events.pipe(
          filter((event) => {
            if (event.type === EventType.RUN_STARTED) {
              currentRunStarted = event.runId === active.runId;
              return false;
            }
            if (!currentRunStarted) {
              return event.type === EventType.RUN_ERROR
                || event.type === EventType.RUN_FINISHED;
            }
            return !("messageId" in event
              && typeof event.messageId === "string"
              && persistedIds.has(event.messageId));
          }),
        );
        return concat(
          from([replayRunStarted(request.threadId, active.runId, latestRun?.selection), snapshot]),
          live,
        );
      }),
      catchError(() => of(safeConnectionError())),
    );
  }

  isRunning(request: AgentRunnerIsRunningRequest): Promise<boolean> {
    return this.delegate.isRunning(request);
  }

  stop(request: AgentRunnerStopRequest): Promise<boolean | undefined> {
    return this.delegate.stop(request);
  }

  async stopTurn(threadId: string, runId: string): Promise<boolean> {
    const active = this.active.get(threadId);
    if (active?.runId !== runId) return false;
    return await this.delegate.stop({ threadId, runId }) === true;
  }

  async shutdown(): Promise<readonly string[]> {
    this.closing = true;
    const running = [...this.active.entries()];
    const settled = Promise.all(running.map(([, run]) => firstValueFrom(
      run.events.pipe(ignoreElements(), endWith(undefined)),
    )));
    await Promise.all(running.map(([threadId, run]) => this.delegate.stop({
      threadId,
      runId: run.runId,
    })));
    await settled;
    return running.map(([, run]) => run.runId);
  }

  async mutateSessionWhenIdle<T>(
    threadId: string,
    operation: () => Promise<T>,
  ): Promise<T> {
    if (this.active.has(threadId) || this.sessionMutations.has(threadId)) {
      throw new SessionActiveRunError();
    }
    this.sessionMutations.add(threadId);
    try {
      return await operation();
    } finally {
      this.sessionMutations.delete(threadId);
    }
  }

  private removeActive(threadId: string, runId: string): void {
    if (this.active.get(threadId)?.runId === runId) this.active.delete(threadId);
  }
}

function replayRunStarted(threadId: string, runId: string, selection: RunSelection | undefined): BaseEvent {
  return { type: EventType.RUN_STARTED, threadId, runId, selection };
}

function replayRunFinished(threadId: string, runId: string): BaseEvent {
  return { type: EventType.RUN_FINISHED, threadId, runId };
}

function replayInterruptFinished(
  threadId: string,
  runId: string,
  question: import("./chat-control.js").PendingQuestion,
): BaseEvent {
  return {
    type: EventType.RUN_FINISHED,
    threadId,
    runId,
    outcome: {
      type: "interrupt",
      interrupts: [{
        id: question.interruptId,
        metadata: {
          mastra: {
            runId,
            suspendPayload: {
              options: question.options ?? undefined,
              question: question.question,
              selectionMode: question.selectionMode === "free_text"
                ? undefined
                : question.selectionMode,
            },
            toolName: "ask_user",
            type: "mastra_suspend",
          },
        },
        reason: "mastra:tool_suspend",
        toolCallId: question.toolCallId,
      }],
    },
  };
}

function safeRunError(): BaseEvent {
  return runFailureEvent("INTERNAL_FAILURE");
}

function safeConnectionError(): BaseEvent {
  return runFailureEvent("AGENT_UNAVAILABLE");
}

function safeRunConflict(): BaseEvent {
  return runFailureEvent("AGENT_RUN_CONFLICT");
}
