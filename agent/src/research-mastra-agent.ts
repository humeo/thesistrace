import { MastraAgent, type MastraAgentConfig } from "@ag-ui/mastra";
import {
  EventType,
  type BaseEvent,
  type RunAgentInput,
} from "@ag-ui/core";
import {
  Observable,
  catchError,
  concatMap,
  defer,
  from,
  map,
  of,
} from "rxjs";

import type { ValidatedChatRun } from "./chat-request.js";
import type { ResearchSessionRepository } from "./session-repository.js";
import type { PersistedTokenUsage } from "./usage-capture.js";

type ResearchExecutionContext = Readonly<{
  agentBuildRevision: string;
  providerModelId: string;
  researcherId: string;
  repository: ResearchSessionRepository;
  run: ValidatedChatRun;
  usage: () => PersistedTokenUsage | undefined;
}>;

export class ResearchMastraAgent extends MastraAgent {
  constructor(
    private readonly bridgeConfig: MastraAgentConfig,
    private readonly execution: ResearchExecutionContext,
  ) {
    super(bridgeConfig);
  }

  override clone(): ResearchMastraAgent {
    const clone = new ResearchMastraAgent(this.bridgeConfig, this.execution);
    if (this.headers !== undefined) clone.headers = { ...this.headers };
    return clone;
  }

  override run(input: RunAgentInput): Observable<BaseEvent> {
    // Runtime request headers are an internal identity transport only. Never
    // forward them as provider model headers.
    this.headers = undefined;
    if (
      input.threadId !== this.execution.run.input.threadId
      || input.runId !== this.execution.run.input.runId
    ) {
      return of(safeRunError());
    }

    return defer(() => this.execution.repository.prepareRun({
      agentBuildRevision: this.execution.agentBuildRevision,
      providerModelId: this.execution.providerModelId,
      researcherId: this.execution.researcherId,
      run: this.execution.run,
    })).pipe(
      concatMap((prepared) => {
        if (prepared.kind === "duplicate") {
          return replayDuplicate(input, prepared.durableMessages, prepared.status);
        }
        return defer(() => super.run(this.execution.run.input)).pipe(
          concatMap((event) => this.persistTerminalEvent(event, input.runId)),
          catchError(() => this.persistFailure(input.runId)),
        );
      }),
      // Preparation failures are request conflicts or storage failures before
      // this invocation owns a new Run. They must never mutate an existing Run.
      catchError(() => of(safeRunError())),
    );
  }

  private persistTerminalEvent(event: BaseEvent, runId: string): Observable<BaseEvent> {
    if (event.type === EventType.RUN_ERROR) {
      return this.persistFailure(runId);
    }
    if (event.type !== EventType.RUN_FINISHED) return of(event);
    return from(
      this.execution.repository.markCompleted(runId, this.execution.usage()),
    ).pipe(
      map(() => event),
    );
  }

  private persistFailure(runId: string): Observable<BaseEvent> {
    return from(
      this.execution.repository
        .markFailed(runId, this.execution.usage())
        .then(() => this.execution.repository.awaitFrameworkRunSettled(runId)),
    ).pipe(
      catchError(() => of(undefined)),
      map(() => safeRunError()),
    );
  }
}

function replayDuplicate(
  input: RunAgentInput,
  messages: readonly import("@ag-ui/core").Message[],
  status: "completed" | "failed" | "running",
): Observable<BaseEvent> {
  const events: BaseEvent[] = [
    {
      type: EventType.RUN_STARTED,
      threadId: input.threadId,
      runId: input.runId,
    },
    {
      type: EventType.MESSAGES_SNAPSHOT,
      messages: [...messages],
    },
  ];
  if (status === "completed") {
    events.push({
      type: EventType.RUN_FINISHED,
      threadId: input.threadId,
      runId: input.runId,
    });
  } else {
    events.push(safeRunError());
  }
  return from(events);
}

function safeRunError(): BaseEvent {
  return {
    type: EventType.RUN_ERROR,
    code: "AGENT_RUN_FAILED",
    message: "The Research Agent could not complete this run.",
  };
}
