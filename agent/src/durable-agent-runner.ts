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
  defer,
  filter,
  from,
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

  constructor(private readonly repository: ResearchSessionRepository) {
    super();
  }

  run(request: AgentRunnerRunRequest): Observable<BaseEvent> {
    if (this.sessionMutations.has(request.threadId)) {
      throw new SessionActiveRunError();
    }
    const current = this.active.get(request.threadId);
    const fingerprint = chatRunFingerprint(request.input);
    if (current?.runId === request.input.runId) {
      if (!current.fingerprint.equals(fingerprint)) {
        throw new Error("ACTIVE_RUN_REQUEST_CONFLICT");
      }
      return current.events;
    }

    const source = this.delegate.run(request);
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
    const active = this.active.get(request.threadId);
    return defer(async () => {
      const [messages, latestRun] = await Promise.all([
        this.repository.durableMessages(request.threadId, researcherId),
        this.repository.latestRun(request.threadId, researcherId),
      ]);
      return { latestRun, messages };
    }).pipe(
      mergeMap(({ latestRun, messages }) => {
        const snapshot: BaseEvent = {
          type: EventType.MESSAGES_SNAPSHOT,
          messages: [...safeBrowserMessages(messages)],
        };
        if (active === undefined) {
          if (latestRun === null) return from([]);
          const started = replayRunStarted(request.threadId, latestRun.id);
          return latestRun.status === "completed"
            ? from([
                started,
                snapshot,
                replayRunFinished(request.threadId, latestRun.id),
              ])
            : from([started, snapshot, safeRunError()]);
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
          from([replayRunStarted(request.threadId, active.runId), snapshot]),
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

function replayRunStarted(threadId: string, runId: string): BaseEvent {
  return { type: EventType.RUN_STARTED, threadId, runId };
}

function replayRunFinished(threadId: string, runId: string): BaseEvent {
  return { type: EventType.RUN_FINISHED, threadId, runId };
}

function safeRunError(): BaseEvent {
  return {
    type: EventType.RUN_ERROR,
    code: "AGENT_RUN_FAILED",
    message: "The Research Agent could not complete this run.",
  };
}

function safeConnectionError(): BaseEvent {
  return {
    type: EventType.RUN_ERROR,
    code: "AGENT_CONNECTION_FAILED",
    message: "The Research Agent session could not be loaded.",
  };
}
