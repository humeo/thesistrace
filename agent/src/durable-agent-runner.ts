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
import { chatRunFingerprint } from "./chat-request.js";
import {
  SessionActiveRunError,
  type ResearchSessionRepository,
} from "./session-repository.js";
import { ResearchA2UIEventProjector } from "./research-a2ui-events.js";
import { runFailureEvent } from "./run-failure.js";
import type { RunSelection } from "../../contracts/agent-run-selection.mjs";

export const RESEARCHER_ID_HEADER = "x-thesistrace-agent-researcher-id";

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
    const fingerprint = chatRunFingerprint(request.input);
    if (current?.runId === request.input.runId) {
      if (!current.fingerprint.equals(fingerprint)) {
        return of(safeRunConflict());
      }
      return current.events;
    }

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
    const source = accepted.pipe(
      concatMap((event) => defer(async () => {
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
        return events;
      }).pipe(mergeMap((events) => from(events)))),
    );
    const events = source.pipe(
      tap({
        complete: () => this.removeActive(request.threadId, request.input.runId),
        error: () => this.removeActive(request.threadId, request.input.runId),
      }),
      shareReplay({ bufferSize: Number.POSITIVE_INFINITY, refCount: false }),
    );
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
          return latestRun.status === "completed"
            ? from([
                started,
                snapshot,
                replayRunFinished(request.threadId, latestRun.id),
              ])
            : from([started, snapshot, runFailureEvent(latestRun.terminalErrorCode)]);
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
    );
  }

  isRunning(request: AgentRunnerIsRunningRequest): Promise<boolean> {
    return this.delegate.isRunning(request);
  }

  stop(request: AgentRunnerStopRequest): Promise<boolean | undefined> {
    return this.delegate.stop(request);
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

function safeRunError(): BaseEvent {
  return runFailureEvent("INTERNAL_FAILURE");
}

function safeConnectionError(): BaseEvent {
  return runFailureEvent("AGENT_UNAVAILABLE");
}

function safeRunConflict(): BaseEvent {
  return runFailureEvent("AGENT_RUN_CONFLICT");
}
