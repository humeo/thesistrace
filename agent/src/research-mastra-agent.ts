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

import {
  A2UI_FRAMEWORK_TOOL_NAMES,
  BrowserEventProjector,
} from "./browser-message-safety.js";
import type { ValidatedChatRun } from "./chat-request.js";
import { projectAskUserInterrupt } from "./chat-control.js";
import type { McpRun } from "./mcp-run.js";
import type { ResearchSessionRepository } from "./session-repository.js";
import type { PersistedTokenUsage } from "./usage-capture.js";
import type { AgentFailureCode } from "../../contracts/agent-failure.mjs";
import type { RunSelection } from "../../contracts/agent-run-selection.mjs";
import { runFailureEvent } from "./run-failure.js";
import { AgentRunFailure, providerFailureCode } from "./run-failure.js";
import type { RunTelemetry } from "./run-telemetry.js";
import { projectResearchA2UIContent } from "../../contracts/research-a2ui.mjs";

type ResearchExecutionContext = Readonly<{
  agentBuildRevision: string;
  failure: () => AgentFailureCode | undefined;
  providerModelId: string;
  mcpRun: () => Promise<McpRun>;
  pendingBridges: Set<Promise<void>>;
  researcherId: string;
  repository: ResearchSessionRepository;
  requestContext: import("@mastra/core/request-context").RequestContext;
  run: ValidatedChatRun;
  runMaxWallMs: number;
  scheduleTitle?: () => Promise<void>;
  selection: RunSelection;
  metrics: () => Readonly<{ generatedBytes: number; steps: number }>;
  telemetry: RunTelemetry;
  usage: () => PersistedTokenUsage | undefined;
}>;

class PersistedFatalToolFailure extends Error {}

export class ResearchMastraAgent extends MastraAgent {
  private readonly abortController = new AbortController();
  private terminalStarted = false;

  constructor(
    private readonly bridgeConfig: MastraAgentConfig,
    private readonly execution: ResearchExecutionContext,
  ) {
    super(bridgeConfig);
    execution.requestContext.set("agentAbortSignal", this.abortController.signal);
  }

  override clone(): ResearchMastraAgent {
    const clone = new ResearchMastraAgent(this.bridgeConfig, this.execution);
    if (this.headers !== undefined) clone.headers = { ...this.headers };
    return clone;
  }

  override abortRun(): void {
    if (!this.terminalStarted) {
      this.abortController.abort(new AgentRunFailure("AGENT_RUN_INTERRUPTED"));
    }
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
      let shouldScheduleTitle = false;
      let titleScheduled = false;
      let activeMcpRun: McpRun | undefined;
      let mcpRunPromise: Promise<McpRun> | undefined;
      let mcpClosePromise: Promise<void> | undefined;
      const observedTools = new Map<string, "mcp" | "a2ui">();
      const finishPendingTools = (failure: AgentFailureCode | null) => {
        for (const kind of observedTools.values()) {
          this.execution.telemetry.toolFinished(failure ?? (kind === "a2ui" ? "TOOL_REJECTION" : "TOOL_ERROR"));
        }
        observedTools.clear();
      };
      // CopilotKit's outer A2UI middleware must see the framework render Tool
      // stream. The Durable Runner is the final boundary that removes those
      // raw payloads after it has produced a validated Activity snapshot.
      const projector = new BrowserEventProjector(A2UI_FRAMEWORK_TOOL_NAMES);
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
      const scheduleTitle = async () => {
        if (!shouldScheduleTitle || titleScheduled || this.execution.scheduleTitle === undefined) return;
        titleScheduled = true;
        try {
          await this.execution.scheduleTitle();
        } catch {
          // Title generation is a separate best-effort operation. It cannot
          // change the already accepted primary Run's terminal outcome.
        }
      };

      const source = defer(async () => {
        const prepared = await this.execution.repository.prepareRun({
          agentBuildRevision: this.execution.agentBuildRevision,
          providerModelId: this.execution.providerModelId,
          researcherId: this.execution.researcherId,
          run: this.execution.run,
        });
        if (prepared.kind === "new") {
          if (prepared.execution === "start") this.execution.telemetry.accepted();
          else this.execution.telemetry.resumed();
        }
        shouldScheduleTitle = prepared.kind === "new"
          && this.execution.run.command === "prompt"
          && prepared.generateTitle;
        // The first accepted message owns title generation, but the title is
        // not part of the Agent Run lifecycle. Start it once admission is
        // durable and never hold RUN_FINISHED/RUN_ERROR or Runner cleanup open
        // for this independent best-effort operation.
        if (shouldScheduleTitle) void scheduleTitle();
        if (disposed && prepared.kind === "new") {
          ownsRun = true;
          this.terminalStarted = true;
          await this.failRun(input.runId, closeMcp, "AGENT_RUN_INTERRUPTED");
          throw new Error("AGENT_RUN_DISPOSED");
        }
        return prepared;
      }).pipe(
        concatMap((prepared) => {
          if (prepared.kind === "duplicate") {
            return replayDuplicate(
              input,
              prepared.durableMessages,
              prepared.status,
              prepared.terminalErrorCode,
              prepared.selection,
              prepared.question,
            );
          }
          ownsRun = true;
          return concat(
            // AG-UI requires every HTTP Run stream, including a Mastra
            // resumeStream request, to open with RUN_STARTED. Answer keeps
            // the exact same durable Turn identity; this is a transport frame,
            // not a second agent_run or a reset of started_at.
            of<BaseEvent>({
              runId: input.runId,
              threadId: input.threadId,
              type: EventType.RUN_STARTED,
              selection: this.execution.selection,
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
              if (this.execution.run.command === "prompt") {
                return {
                  ...this.execution.run.input,
                  messages: [this.execution.run.userMessage],
                };
              }
              return { ...this.execution.run.input, messages: [] };
            }).pipe(
              concatMap((authoritativeInput) => this.runBridge(authoritativeInput)),
              // The durable acceptance event above is the sole RUN_STARTED.
              concatMap((event) => {
                if (event.type === EventType.RUN_STARTED) return from([]);
                if (event.type === EventType.TOOL_CALL_START
                  && typeof event.toolCallId === "string" && typeof event.toolCallName === "string") {
                  if (activeMcpRun !== undefined && Object.hasOwn(activeMcpRun.tools, event.toolCallName)) observedTools.set(event.toolCallId, "mcp");
                  else if (A2UI_FRAMEWORK_TOOL_NAMES.has(event.toolCallName)) observedTools.set(event.toolCallId, "a2ui");
                }
                const toolCallId = event.type === EventType.TOOL_CALL_RESULT
                  && typeof event.toolCallId === "string"
                  ? event.toolCallId
                  : undefined;
                const toolFailure = toolCallId === undefined
                  ? undefined
                  : activeMcpRun?.toolFailure(toolCallId);
                if (toolCallId !== undefined && observedTools.has(toolCallId)) {
                  const failure = observedTools.get(toolCallId) === "a2ui"
                    ? a2uiFailure(event.content) : toolFailure?.code ?? null;
                  observedTools.delete(toolCallId);
                  this.execution.telemetry.toolFinished(failure);
                }
                if (toolFailure?.fatal === true) {
                  this.terminalStarted = true;
                  finishPendingTools(toolFailure.code);
                  // Emit the safe failed Tool result, persist the terminal Run
                  // failure, then unsubscribe from any already-buffered model
                  // output. This prevents a later RUN_FINISHED from racing the
                  // transport failure and overwriting it as completed.
                  return concat(
                    of(event),
                    this.persistFailure(input.runId, closeMcp, toolFailure.code, toolCallId),
                    throwError(() => new PersistedFatalToolFailure()),
                  );
                }
                if (
                  event.type === EventType.RUN_ERROR
                  || event.type === EventType.RUN_FINISHED
                ) {
                  this.terminalStarted = true;
                  // Native validation may emit tool-error with no AG-UI Tool
                  // Result. Its pending invocation still needs one observation.
                  finishPendingTools(this.execution.failure() ?? (event.type === EventType.RUN_ERROR ? "INTERNAL_FAILURE" : null));
                }
                return this.persistTerminalEvent(
                  event,
                  input.runId,
                  closeMcp,
                );
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

      const boundedRun = withTotalTimeout(source, this.execution.runMaxWallMs, this.abortController).pipe(
        // Once prepareRun inserts a Run, every later failure owns that row and
        // must durably terminate it. Preparation conflicts never mutate a Run.
        catchError((error) => {
          if (error instanceof PersistedFatalToolFailure) return from([]);
          if (!ownsRun) {
            return from(closeMcp()).pipe(map(() => runFailureEvent(providerFailureCode(error))));
          }
          this.terminalStarted = true;
          const code = this.execution.failure() ?? providerFailureCode(error);
          finishPendingTools(code);
          return this.persistFailure(input.runId, closeMcp, code);
        }),
      );

      return boundedRun.pipe(
        finalize(() => {
          disposed = true;
          if (ownsRun && !this.terminalStarted) {
            this.terminalStarted = true;
            finishPendingTools("AGENT_RUN_INTERRUPTED");
            this.abortController.abort(new AgentRunFailure("AGENT_RUN_INTERRUPTED"));
            void this.failRun(input.runId, closeMcp, "AGENT_RUN_INTERRUPTED");
          } else {
            void closeMcp();
          }
        }),
      );
    });
  }

  private runBridge(input: RunAgentInput): Observable<BaseEvent> {
    return new Observable((subscriber) => {
      let completed = false;
      let settle!: () => void;
      const drained = new Promise<void>((resolve) => { settle = resolve; });
      this.execution.pendingBridges.add(drained);
      const finish = () => {
        completed = true;
        this.execution.pendingBridges.delete(drained);
        settle();
      };
      // The pinned bridge's Observable teardown does not await its async
      // stream reader or final Memory snapshot. Keep that reader subscribed
      // until it really terminates; cancellation is propagated to Mastra via
      // abortSignal, while closed downstream subscribers discard late output.
      // The Host drains these readers before closing PostgreSQL.
      super.run(input).subscribe({
        complete: () => { finish(); subscriber.complete(); },
        error: (error) => { finish(); subscriber.error(error); },
        next: (event) => subscriber.next(event),
      });
      return () => {
        if (!completed) this.abortController.abort(new AgentRunFailure("AGENT_RUN_INTERRUPTED"));
      };
    });
  }

  private persistTerminalEvent(
    event: BaseEvent,
    runId: string,
    closeMcp: () => Promise<void>,
  ): Observable<BaseEvent> {
    const failure = this.execution.failure();
    if (event.type === EventType.RUN_ERROR || (event.type === EventType.RUN_FINISHED && failure !== undefined)) {
      return this.persistFailure(runId, closeMcp, failure ?? "INTERNAL_FAILURE");
    }
    if (event.type !== EventType.RUN_FINISHED) return of(event);
    const question = projectAskUserInterrupt(event, runId);
    if (question !== null) {
      const metrics = this.execution.metrics();
      return from(
        this.execution.repository
          .markWaiting(
            runId,
            this.execution.usage(),
            metrics.steps,
            metrics.generatedBytes,
            question,
          )
          .then(() => this.execution.telemetry.waiting())
          .then(closeMcp),
      ).pipe(map(() => event));
    }
    const metrics = this.execution.metrics();
    return from(
      this.execution.repository
        .markCompleted(runId, this.execution.usage(), metrics.steps, metrics.generatedBytes)
        .then((status) => status === "stopped"
          ? this.execution.telemetry.stopped()
          : this.execution.telemetry.finished(null))
        .then(closeMcp),
    ).pipe(
      map(() => event),
    );
  }

  private persistFailure(
    runId: string,
    closeMcp: () => Promise<void>,
    code: AgentFailureCode,
    toolCallId?: string,
  ): Observable<BaseEvent> {
    return from(this.failRun(runId, closeMcp, code, toolCallId)).pipe(
      map(() => runFailureEvent(code)),
    );
  }

  private async failRun(
    runId: string,
    closeMcp: () => Promise<void>,
    code: AgentFailureCode,
    toolCallId?: string,
  ): Promise<void> {
    const closePromise = closeMcp();
    let stopped = false;
    try {
      const metrics = this.execution.metrics();
      const [status] = await Promise.all([
        this.execution.repository.markFailed(
          runId,
          this.execution.usage(),
          code,
          metrics.steps,
          metrics.generatedBytes,
        ),
        closePromise,
      ]);
      stopped = status === "stopped";
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
    } finally {
      if (stopped) this.execution.telemetry.stopped();
      else this.execution.telemetry.finished(code);
    }
  }
}

function replayDuplicate(
  input: RunAgentInput,
  messages: readonly import("@ag-ui/core").Message[],
  status: import("./chat-control.js").TurnStatus,
  terminalErrorCode: string | null,
  selection: RunSelection,
  question: import("./chat-control.js").PendingQuestion | null,
): Observable<BaseEvent> {
  const events: BaseEvent[] = [
    {
      type: EventType.RUN_STARTED,
      threadId: input.threadId,
      runId: input.runId,
      selection,
    },
    {
      type: EventType.MESSAGES_SNAPSHOT,
      messages: [...messages],
    },
  ];
  if (status === "completed" || status === "stopped") {
    events.push({
      type: EventType.RUN_FINISHED,
      threadId: input.threadId,
      runId: input.runId,
    });
  } else if (status === "waiting_for_user" && question !== null) {
    events.push({
      type: EventType.RUN_FINISHED,
      threadId: input.threadId,
      runId: input.runId,
      outcome: {
        type: "interrupt",
        interrupts: [{
          id: question.interruptId,
          metadata: {
            mastra: {
              runId: input.runId,
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
    });
  } else {
    events.push(runFailureEvent(
      status === "failed" ? terminalErrorCode : "AGENT_RUN_CONFLICT",
    ));
  }
  return from(events);
}

function safeRunError(): BaseEvent {
  return runFailureEvent("INTERNAL_FAILURE");
}

function a2uiFailure(content: unknown): AgentFailureCode | null {
  try {
    const projected = projectResearchA2UIContent(typeof content === "string" ? JSON.parse(content) : undefined);
    return projected.valid && projected.kind === "ready" ? null : "TOOL_REJECTION";
  } catch { return "TOOL_REJECTION"; }
}

function withTotalTimeout(
  source: Observable<BaseEvent>,
  timeoutMs: number,
  abortController: AbortController,
): Observable<BaseEvent> {
  return new Observable((subscriber) => {
    const signal = abortController.signal;
    if (signal.aborted) {
      subscriber.error(signal.reason);
      return;
    }
    const subscription = source.subscribe({
      complete: () => subscriber.complete(),
      error: (error) => subscriber.error(error),
      next: (event) => subscriber.next(event),
    });
    const onAbort = () => {
      subscription.unsubscribe();
      subscriber.error(signal.reason);
    };
    signal.addEventListener("abort", onAbort, { once: true });
    const timer = setTimeout(() => {
      abortController.abort(new AgentRunFailure("AGENT_LIMIT"));
    }, timeoutMs);
    return () => {
      clearTimeout(timer);
      signal.removeEventListener("abort", onAbort);
      subscription.unsubscribe();
    };
  });
}
