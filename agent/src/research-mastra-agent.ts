import { MastraAgent, type MastraAgentConfig } from "@ag-ui/mastra";
import {
  EventType,
  type BaseEvent,
  type RunAgentInput,
} from "@ag-ui/core";
import {
  Observable,
  catchError,
  concat,
  concatMap,
  defer,
  finalize,
  from,
  map,
  of,
  throwError,
} from "rxjs";

import { BrowserEventProjector } from "./browser-message-safety.js";
import type { ValidatedChatRun } from "./chat-request.js";
import type { McpRun } from "./mcp-run.js";
import type { ResearchSessionRepository } from "./session-repository.js";
import type { PersistedTokenUsage } from "./usage-capture.js";

type ResearchExecutionContext = Readonly<{
  agentBuildRevision: string;
  providerModelId: string;
  mcpRun: () => Promise<McpRun>;
  researcherId: string;
  repository: ResearchSessionRepository;
  requestContext: import("@mastra/core/request-context").RequestContext;
  run: ValidatedChatRun;
  runMaxWallMs: number;
  usage: () => PersistedTokenUsage | undefined;
}>;

class PersistedFatalToolFailure extends Error {}

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

    return defer(() => {
      let disposed = false;
      let ownsRun = false;
      let terminalStarted = false;
      let activeMcpRun: McpRun | undefined;
      let mcpRunPromise: Promise<McpRun> | undefined;
      let mcpClosePromise: Promise<void> | undefined;
      const projector = new BrowserEventProjector();
      const closeMcp = () => {
        this.execution.requestContext.set("mcpTools", {});
        mcpClosePromise ??= (async () => {
          try {
            const mcpRun = await mcpRunPromise;
            await mcpRun?.close();
          } catch {
            // Preparation and disconnect details are intentionally private.
          }
        })();
        return mcpClosePromise;
      };

      const source = defer(async () => {
        const prepared = await this.execution.repository.prepareRun({
          agentBuildRevision: this.execution.agentBuildRevision,
          providerModelId: this.execution.providerModelId,
          researcherId: this.execution.researcherId,
          run: this.execution.run,
        });
        if (disposed && prepared.kind === "new") {
          ownsRun = true;
          terminalStarted = true;
          await this.failRun(input.runId, closeMcp);
          throw new Error("AGENT_RUN_DISPOSED");
        }
        return prepared;
      }).pipe(
        concatMap((prepared) => {
          if (prepared.kind === "duplicate") {
            return replayDuplicate(input, prepared.durableMessages, prepared.status);
          }
          ownsRun = true;
          return concat(
            of<BaseEvent>({
              runId: input.runId,
              threadId: input.threadId,
              type: EventType.RUN_STARTED,
            }),
            defer(async () => {
              mcpRunPromise = this.execution.mcpRun();
              const mcpRun = await mcpRunPromise;
              if (mcpClosePromise !== undefined) {
                await mcpClosePromise;
                throw new Error("AGENT_RUN_DISPOSED");
              }
              activeMcpRun = mcpRun;
              this.execution.requestContext.set("mcpRun", mcpRun);
              this.execution.requestContext.set("mcpTools", mcpRun.tools);
              return {
                ...this.execution.run.input,
                // prepareRun already compared the browser transcript with the
                // server projection. Pass only the new user message so Mastra
                // recalls prior Tool arguments/results from authoritative
                // Memory; browser-safe synthetic Tool messages never re-enter
                // the model or persistence path.
                messages: [this.execution.run.latestUserMessage],
              };
            }).pipe(
              concatMap((authoritativeInput) => super.run(authoritativeInput)),
              // The durable acceptance event above is the sole RUN_STARTED.
              concatMap((event) => {
                if (event.type === EventType.RUN_STARTED) return from([]);
                const toolCallId = event.type === EventType.TOOL_CALL_RESULT
                  && typeof event.toolCallId === "string"
                  ? event.toolCallId
                  : undefined;
                const toolFailure = toolCallId === undefined
                  ? undefined
                  : activeMcpRun?.toolFailure(toolCallId);
                if (toolFailure === "transport") {
                  terminalStarted = true;
                  // Emit the safe failed Tool result, persist the terminal Run
                  // failure, then unsubscribe from any already-buffered model
                  // output. This prevents a later RUN_FINISHED from racing the
                  // transport failure and overwriting it as completed.
                  return concat(
                    of(event),
                    this.persistFailure(input.runId, closeMcp, toolCallId),
                    throwError(() => new PersistedFatalToolFailure()),
                  );
                }
                if (
                  event.type === EventType.RUN_ERROR
                  || event.type === EventType.RUN_FINISHED
                ) {
                  terminalStarted = true;
                }
                return this.persistTerminalEvent(event, input.runId, closeMcp);
              }),
            ),
          );
        }),
        concatMap((event) => {
          const toolFailed = event.type === EventType.TOOL_CALL_RESULT
            && typeof event.toolCallId === "string"
            && activeMcpRun?.toolFailure(event.toolCallId) !== undefined;
          return from(projector.project(event, toolFailed));
        }),
      );

      return withTotalTimeout(source, this.execution.runMaxWallMs).pipe(
        // Once prepareRun inserts a Run, every later failure owns that row and
        // must durably terminate it. Preparation conflicts never mutate a Run.
        catchError((error) => {
          if (error instanceof PersistedFatalToolFailure) return from([]);
          if (!ownsRun) {
            return from(closeMcp()).pipe(map(() => safeRunError()));
          }
          terminalStarted = true;
          return this.persistFailure(input.runId, closeMcp);
        }),
        finalize(() => {
          disposed = true;
          if (ownsRun && !terminalStarted) {
            terminalStarted = true;
            void this.failRun(input.runId, closeMcp);
          } else {
            void closeMcp();
          }
        }),
      );
    });
  }

  private persistTerminalEvent(
    event: BaseEvent,
    runId: string,
    closeMcp: () => Promise<void>,
  ): Observable<BaseEvent> {
    if (event.type === EventType.RUN_ERROR) {
      return this.persistFailure(runId, closeMcp);
    }
    if (event.type !== EventType.RUN_FINISHED) return of(event);
    return from(
      this.execution.repository
        .markCompleted(runId, this.execution.usage())
        .then(closeMcp),
    ).pipe(
      map(() => event),
    );
  }

  private persistFailure(
    runId: string,
    closeMcp: () => Promise<void>,
    toolCallId?: string,
  ): Observable<BaseEvent> {
    return from(this.failRun(runId, closeMcp, toolCallId)).pipe(
      map(() => safeRunError()),
    );
  }

  private async failRun(
    runId: string,
    closeMcp: () => Promise<void>,
    toolCallId?: string,
  ): Promise<void> {
    const closePromise = closeMcp();
    try {
      await Promise.all([
        this.execution.repository.markFailed(runId, this.execution.usage()),
        closePromise,
      ]);
      if (toolCallId !== undefined) {
        await this.execution.repository.awaitDurableToolResult(
          this.execution.run.input.threadId,
          this.execution.researcherId,
          toolCallId,
        );
      }
      await this.execution.repository.awaitFrameworkRunSettled(runId);
    } catch {
      await closePromise;
    }
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

function withTotalTimeout(
  source: Observable<BaseEvent>,
  timeoutMs: number,
): Observable<BaseEvent> {
  return new Observable((subscriber) => {
    const subscription = source.subscribe({
      complete: () => subscriber.complete(),
      error: (error) => subscriber.error(error),
      next: (event) => subscriber.next(event),
    });
    const timer = setTimeout(() => {
      subscription.unsubscribe();
      subscriber.error(new Error("AGENT_RUN_TIMEOUT"));
    }, timeoutMs);
    return () => {
      clearTimeout(timer);
      subscription.unsubscribe();
    };
  });
}
