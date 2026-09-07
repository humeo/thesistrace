import { SessionModelRecovery } from "./session-model-recovery.js";
import { invalidRecoveryMessageIds } from "./model-step-recovery.js";
import { isSessionControlMessageId, sessionControlMessage, sessionControlMessageId } from "./session-control-message.js";
import { ContextLanguageModel } from "./context-language-model.js";
import { SessionContextController } from "./session-context-controller.js";
import { Agent } from "@mastra/core/agent";
import { noopLogger } from "@mastra/core/logger";
import { Mastra } from "@mastra/core/mastra";
import { RequestContext } from "@mastra/core/request-context";
import { askUserTool } from "@mastra/core/tools";
import type { Memory } from "@mastra/memory";
import { PostgresStore } from "@mastra/pg";
import {
  CopilotRuntime,
  createCopilotRuntimeHandler,
} from "@copilotkit/runtime/v2";
import { MastraAgent } from "@ag-ui/mastra";

import {
  RESEARCH_A2UI_CATALOG_ID,
  RESEARCH_A2UI_INLINE_CATALOG,
} from "../../contracts/research-a2ui.mjs";

import {
  ChatRequestError,
  isChatThreadId,
  readThreadId,
  readValidatedChatRun,
  type ValidatedChatRun,
} from "./chat-request.js";
import {
  ChatControlError,
  type CommandReceipt,
  type TimelineCursor,
  type TimelinePage,
} from "./chat-control.js";
import type { AgentSettings } from "./config.js";
import {
  createAgentPool,
  createAgentReadinessPool,
} from "./database.js";
import {
  DurableResearchAgentRunner,
  RESEARCHER_ID_HEADER,
} from "./durable-agent-runner.js";
import {
  RegisteredModelRuntime,
  type ResolvedModelSelection,
} from "./model-runtime.js";
import { createResearchMemory } from "./research-memory.js";
import {
  createMcpRunFactory,
  type DiscoveredMcpTools,
  type McpRunFactory,
} from "./mcp-run.js";
import { ResearchMastraAgent } from "./research-mastra-agent.js";
import { MastraTurnControl } from "./mastra-turn-control.js";
import {
  RESEARCH_A2UI_TOOL_NAME,
  researchA2UITool,
} from "./research-a2ui-tool.js";
import { createAgentReadiness } from "./readiness.js";
import {
  ResearchSessionRepository,
  ChatRunConflictError,
  SessionActiveRunError,
  SessionNotFoundError,
  type RenamedSession,
  type SessionPage,
} from "./session-repository.js";
import type { SessionCursor } from "./session-management.js";
import { SessionTitleGenerator } from "./session-title.js";
import type { VerifiedResearcher } from "./session-verifier.js";
import { verifyAgentSchema } from "./schema-contract.js";
import { RunUsageCapture } from "./usage-capture.js";
import { AGENT_LIMITS, RunModelObservation } from "./guarded-language-model.js";
import { providerFailureCode } from "./run-failure.js";
import { agentTraceId, createRunTelemetry, type AgentTelemetryWriter } from "./run-telemetry.js";
import { PRIVACY_CANARIES } from "./scripted-privacy-model.js";

const RESEARCH_AGENT_ID = "research";
const RESEARCH_AGENT_INSTRUCTIONS = `You are the ThesisTrace Research Agent.
Help a researcher turn an investment idea into a precise, testable Alpha research plan.
Use only the Tools supplied by the current authenticated MCP discovery. You own Tool selection, arguments, Folder choice, Formula authoring and correction, Research type, dates, universe, neutralization, Strategy parameters, polling decisions, Result-section selection, and the final response.
Use reliable platform defaults when the investment intent is clear. Ask a focused follow-up only when missing intent would materially change the Research; do not turn clear requests into a parameter wizard.
Treat Formula diagnostics and admission rejection as structured correctable results. Preserve stable authentication, authorization, lifecycle, transient, and internal Tool error meanings. Retry a transient Tool call only when appropriate, after its retry_after_seconds guidance, with the exact same arguments.
For every effectful Tool call, derive a caller-stable request_id from the current Agent Run identity plus an operation and revision. Reuse that exact request_id and command after an uncertain response; allocate a new revision only when a structured rejection requires a changed command.
State assumptions and distinguish proposals from persisted Research facts. Never claim that a ResearchRun or Result exists unless an authoritative Tool result confirms it. Once Research is admitted, remember that the Core Worker continues independently if this Agent Run ends.
For comparisons, use the discovered Batch capabilities with explicit ordered item keys. Keep those keys and the request_id unchanged when replaying the same admission. Follow the current Tool schema, including Core-owned Research organization; do not invent a Folder argument. A Batch coordinates ordinary Child ResearchRuns, never owns a synthetic aggregate Result. Read each required Child Result section, follow opaque pagination cursors without changing its query, and explain partial failures without inventing missing metrics. Use existing A2UI primitives to show the comparison objective, authoritative Batch identity, ordered child results, and safe ResearchRun navigation. Poll only within the current Agent Run bounds; Core continues independently. Never create a background watcher or claim Chat deletion cancels Research.
For DailyTrack, verify a succeeded Strategy Backtest Origin and reuse an existing Track for that Origin. Follow discovered Tool descriptions and current action eligibility; Refresh is for active, lagging, idle Tracks and Retry is for blocked Tracks. DailyTrack Refresh means an explicit command that queues a Tracking Advance: do not claim to execute it unless current Discovery provides that command. Reloading the current view uses only lifecycle and Result reads and must not be described as submitting DailyTrack Refresh. The existing Tracking Worker is independent. Preserve request_id and arguments on uncertain Start, Refresh, or Retry responses. Read bounded Observation pages without claiming that a partial page contains the latest Observation. Distinguish the changing current Track view from its fixed Origin and from immutable Research Results; do not expose checkpoint, lease, or storage internals. Use the existing A2UI primitives for Track identity, Origin, phase, data/observation dates, block reason, metrics, provenance, and DailyTrack navigation. Agent completion, disconnect, failure, and Chat deletion never stop a Track.
Use render_a2ui when a concrete Alpha proposal or authoritative Result benefits from structured display. Intermediate progress should use concise ordinary text and Tool activity, not progress-only surfaces. A proposal is Chat-owned and must never imply persistence. Populate ResearchRun identity, status, Formula, Result metrics, sections, provenance, and links only from Tool results from this run or authoritative memory. Keep an ordinary concise text explanation alongside the surface.
Generate each surface with a unique lowercase-hyphenated surfaceId and a flat component array rooted at id "root". Use only registered components and literal props; omit data or pass an empty object. Do not emit bindings, actions, events, functions, HTML, CSS, JavaScript, media, network requests, editable controls, submit, retry, cancel, stop, or delete. Navigation hrefs must be registered ThesisTrace routes, and every non-root component must be referenced exactly once by a Row or Column.`;

export type ResearchRuntime = Readonly<{
  close: () => Promise<void>;
  deleteSession: (threadId: string, researcher: VerifiedResearcher) => Promise<void>;
  handle: (request: Request, researcher: VerifiedResearcher) => Promise<Response>;
  commandReceipt: (
    threadId: string,
    commandId: string,
    researcher: VerifiedResearcher,
  ) => Promise<CommandReceipt>;
  preference: (
    threadId: string,
    researcher: VerifiedResearcher,
  ) => Promise<Readonly<{ model_key: string; reasoning_effort: string }> | null>;
  renameSession: (
    threadId: string,
    researcher: VerifiedResearcher,
    title: string,
    expectedVersion: Date,
  ) => Promise<RenamedSession>;
  ready: () => Promise<boolean>;
  session: (
    threadId: string,
    researcher: VerifiedResearcher,
  ) => Promise<import("./session-repository.js").SessionSummary>;
  sessions: (
    cursor: SessionCursor | undefined,
    researcher: VerifiedResearcher,
  ) => Promise<SessionPage>;
  steer: (
    threadId: string,
    researcher: VerifiedResearcher,
    input: import("./chat-control.js").SteerInput,
  ) => Promise<CommandReceipt>;
  stop: (
    threadId: string,
    researcher: VerifiedResearcher,
    input: import("./chat-control.js").StopInput,
  ) => Promise<CommandReceipt>;
  timeline: (
    threadId: string,
    researcher: VerifiedResearcher,
    before: TimelineCursor | undefined,
    limit: number,
  ) => Promise<TimelinePage>;
}>;
export type ResearchRuntimeDependencies = Readonly<{
  mcpRunFactory?: McpRunFactory;
  readinessFetch?: typeof globalThis.fetch;
  telemetry?: AgentTelemetryWriter;
}>;

export async function createResearchRuntime(
  settings: AgentSettings,
  dependencies: ResearchRuntimeDependencies = {},
): Promise<ResearchRuntime> {
  const pool = createAgentPool(settings.databaseUrl);
  try {
    await verifyAgentSchema(pool);
  } catch (error) {
    await pool.end();
    throw error;
  }

  const repository = new ResearchSessionRepository(pool);
  try {
    await repository.failInterruptedRunsAfterHostRestart();
  } catch (error) {
    await pool.end();
    throw error;
  }
  const titleGenerator = new SessionTitleGenerator(repository);
  const readinessPool = createAgentReadinessPool(settings.databaseUrl);
  const readiness = createAgentReadiness(settings, readinessPool, {
    fetch: dependencies.readinessFetch,
  });
  const modelRuntime = new RegisteredModelRuntime(settings.modelRegistry);
  const mcpRunFactory = dependencies.mcpRunFactory ?? createMcpRunFactory(settings);
  const storage = new PostgresStore({
    disableInit: true,
    id: "thesistrace-agent-memory",
    pool,
    schemaName: "agent",
  });
  const memories = new Map<string, Memory>();
  const agent = new Agent({
    defaultOptions: ({ requestContext }) => {
      const observation = requestContext.get<string, RunModelObservation | undefined>("modelObservation");
      return {
        abortSignal: requestContext.get<string, AbortSignal | undefined>("agentAbortSignal"),
        // Override framework defaults without imposing a model-call count limit.
        maxSteps: Number.POSITIVE_INFINITY,
        // The Provider boundary reduces this configured allowance to fit the actual input.
        modelSettings: { maxOutputTokens: selectionFrom(requestContext).model.maxOutputTokens, timeout: { stepMs: AGENT_LIMITS.providerCallMs } },
        maxProcessorRetries: 1,
        onError: ({ error }: { error: unknown }) => { observation?.fail(providerFailureCode(error)); },
        providerOptions: selectionFrom(requestContext).providerOptions,
        // Completed tool steps must be durable while a later MCP call is still
        // running so their validated surfaces can reference persisted messages.
        savePerStep: true,
        // A transport/protocol failure is converted into one safe Tool result so
        // AG-UI can close that exact invocation. Stop before another provider
        // step; ResearchMastraAgent will persist the failed product Run.
        stopWhen: () => mcpRunFrom(requestContext)?.hasFatalToolFailure() === true,
      };
    },
    id: RESEARCH_AGENT_ID,
    instructions: ({ requestContext }) => researchAgentInstructions(requestContext),
    maxRetries: 0,
    memory: ({ requestContext }) => {
      const selection = selectionFrom(requestContext);
      const key = `${selection.model.key}:${selection.effort}`;
      let memory = memories.get(key);
      if (memory === undefined) {
        memory = createResearchMemory(storage);
        memories.set(key, memory);
      }
      return memory;
    },
    inputProcessors: () => [{
      id: "session-context-input",
      processInputStep: async ({ messageList, requestContext, rotateResponseMessageId, retryCount }) => {
        if (!requestContext) throw new Error("SESSION_CONTEXT_IDENTITY_MISSING");
        const threadId = requestContext.get<string, string>("contextThreadId");
        const researcherId = requestContext.get<string, string>("contextResearcherId");
        const runId = requestContext.get<string, string>("agentRunId");
        const abortSignal = requestContext.get<string, AbortSignal>("agentAbortSignal");
        if (!threadId || !researcherId || !runId || !abortSignal) throw new Error("SESSION_CONTEXT_IDENTITY_MISSING");
        abortSignal.throwIfAborted();
        await assertOwnedThread(repository, threadId, researcherId);
        const recoveries = await repository.modelStepRecoveries(threadId, researcherId);
        messageList.removeByIds(invalidRecoveryMessageIds(recoveries));
        const runObservation = requestContext.get<string, RunModelObservation | undefined>("modelObservation");
        if (runObservation) runObservation.recoveryAttempts = recoveries.filter(record => record.runId === runId)
          .reduce((total, record) => total + record.attempts, 0);
        if (!messageList.get.all.db().some((message) => message.id === sessionControlMessageId(runId))) {
          const lastCreated = Math.max(Date.now(), ...messageList.get.all.db().map((message) => message.createdAt.getTime() + 1));
          messageList.add(sessionControlMessage({ runId, threadId, researcherId, createdAt: new Date(lastCreated),
            continueIntent: requestContext.get("continueIntent") === true }), "context", { merge: false });
        }
        if (!rotateResponseMessageId) throw new Error("SESSION_CONTEXT_RESPONSE_BOUNDARY_MISSING");
        const freshResponseId = rotateResponseMessageId();
        const messages = messageList.get.all.db().filter((message) => message.role !== "system" && message.content.parts.length > 0);
        if (messages.some((message) => message.threadId !== threadId || message.resourceId !== researcherId)) {
          throw new Error("SESSION_CONTEXT_SOURCE_IDENTITY_MISMATCH");
        }
        // Persist the complete current tool batch before freezing its source watermark.
        await createResearchMemory(storage).saveMessages({ messages });
        requestContext.set("contextCurrentRequestId", [...messages].reverse().find((message) => message.role === "user" && !isSessionControlMessageId(message.id))?.id);
        if (!requestContext.get("sessionContextController")) requestContext.set("sessionContextController", new SessionContextController({
          repository, threadId, researcherId, runId, selection: selectionFrom(requestContext),
          storage, mastra, requestContext, abortSignal,
        }));
        let recovery = requestContext.get<string, SessionModelRecovery | undefined>("sessionModelRecovery");
        if (!recovery) {
          const observation = requestContext.get<string, RunModelObservation | undefined>("modelObservation");
          const context = requestContext.get<string, SessionContextController>("sessionContextController");
          if (!observation || !context) throw new Error("SESSION_CONTEXT_IDENTITY_MISSING");
          recovery = new SessionModelRecovery({ repository, memory: createResearchMemory(storage), threadId, researcherId, runId,
            selection: selectionFrom(requestContext), context, observation, abortSignal,
            notify: claimed => requestContext.get<string, ((claimed: boolean) => void) | undefined>("notifyModelRecovery")?.(claimed) });
          requestContext.set("sessionModelRecovery", recovery);
        }
        return { messageId: recovery.responseMessageId(freshResponseId, retryCount) };
      },
    }],
    outputProcessors: [{ id: "session-replacement-completion", processOutputStep: async ({ requestContext, finishReason, messageList }) => {
      await requestContext?.get<string, SessionModelRecovery | undefined>("sessionModelRecovery")?.completeResponse(finishReason);
      return messageList;
    } }],
    errorProcessors: [{ id: "session-model-recovery", processAPIError: async ({ error, messageList, requestContext }) => {
      const recovery = requestContext?.get<string, SessionModelRecovery | undefined>("sessionModelRecovery");
      if (!recovery) throw error;
      return recovery.handle(error, messageList, requestContext?.get<string, string | undefined>("contextCurrentRequestId"));
    } }],
    model: ({ requestContext }) => new ContextLanguageModel(selectionFrom(requestContext).languageModel, async (request) => {
      const controller = requestContext.get<string, SessionContextController | undefined>("sessionContextController");
      if (!controller) throw new Error("SESSION_CONTEXT_INPUT_NOT_PREPARED");
      return controller.prepare(request, requestContext.get<string, string | undefined>("contextCurrentRequestId"));
    }),
    name: "ThesisTrace Research Agent",
    tools: ({ requestContext }) => researchToolsFrom(requestContext),
  });
  const mastra = new Mastra({
    agents: { [RESEARCH_AGENT_ID]: agent },
    // Framework validation and provider logs can contain complete Tool input,
    // conversation content, and credentials. Do not maintain a message-name
    // denylist: durable product Run metadata is the safe diagnostic boundary.
    logger: noopLogger,
    recovery: { durableAgents: "off" },
    storage,
  });
  const runner = new DurableResearchAgentRunner(repository);
  const pendingBridges = new Set<Promise<void>>();
  const runtime = new CopilotRuntime({
    a2ui: {
      agents: [RESEARCH_AGENT_ID],
      a2uiToolNames: [RESEARCH_A2UI_TOOL_NAME],
      defaultCatalogId: RESEARCH_A2UI_CATALOG_ID,
      injectA2UITool: false,
      recovery: {
        debugExposure: "hidden",
        maxAttempts: 2,
        showProgressTokens: false,
      },
      schema: RESEARCH_A2UI_INLINE_CATALOG,
    },
    agents: async ({ request }) => {
      const researcherId = request.headers.get(RESEARCHER_ID_HEADER);
      if (researcherId === null) throw new SessionNotFoundError();

      const isRun = new URL(request.url).pathname.endsWith(
        `/agent/${RESEARCH_AGENT_ID}/run`,
      );
      const validated = isRun
        ? await readValidatedChatRun(request, settings.modelRegistry)
        : undefined;
      const resumedExecution = validated?.command === "answer"
        ? await repository.runExecution(
            validated,
            researcherId,
          )
        : undefined;
      const usageCapture = validated === undefined
        ? undefined
        : new RunUsageCapture(resumedExecution?.usage);
      const modelObservation = usageCapture === undefined
        ? undefined
        : new RunModelObservation(usageCapture, {
            generatedBytes: resumedExecution?.generatedBytes,
            steps: resumedExecution?.stepCount,
          });
      const selection = validated === undefined
        ? modelRuntime.resolve(
            settings.modelRegistry.defaultModelKey,
            settings.modelRegistry.models.find(
              (candidate) => candidate.key === settings.modelRegistry.defaultModelKey,
            )?.defaultReasoningEffort ?? "medium",
          )
        : modelRuntime.resolve(
            validated.command === "answer"
              ? resumedExecution?.selection.modelKey ?? ""
              : validated.modelKey,
            validated.command === "answer"
              ? resumedExecution?.selection.reasoningEffort ?? "medium"
              : validated.reasoningEffort,
            modelObservation,
          );
      if (
        resumedExecution !== undefined
        && selection.model.providerModelId !== resumedExecution.selection.providerModelId
      ) {
        throw new Error("RESUMED_MODEL_CAPABILITY_CHANGED");
      }
      const titleSelection = validated?.command !== "prompt"
        ? undefined
        : modelRuntime.resolve(validated.modelKey, validated.reasoningEffort);
      const requestContext = createRequestContext(selection);
      requestContext.set("modelObservation", modelObservation);
      requestContext.set("continueIntent", validated?.command === "continue");

      if (validated === undefined) {
        return {
          [RESEARCH_AGENT_ID]: new MastraAgent({
            agent,
            agentId: RESEARCH_AGENT_ID,
            a2ui: researchA2UIBridgeConfig(),
            emitInterruptOutcome: true,
            // This controls AG-UI activity exposure, not server-side compression.
            observationalMemory: false,
            requestContext,
            resourceId: researcherId,
          }),
        };
      }
      if (usageCapture === undefined || modelObservation === undefined) {
        throw new Error("RUN_USAGE_CAPTURE_NOT_CREATED");
      }
      if (validated.command === "prompt" && titleSelection === undefined) {
        throw new Error("TITLE_MODEL_SELECTION_NOT_CREATED");
      }

      return {
        [RESEARCH_AGENT_ID]: createRunAgent({
          agentBuildRevision: settings.agentBuildRevision,
          mastra,
          modelObservation,
          pendingBridges,
          mcpRun: () => mcpRunFactory(
            new Headers(request.headers),
            validated.input.runId,
          ),
          providerModelId: selection.model.providerModelId,
          repository,
          requestContext,
          researcherId,
          run: validated,
          runMaxWallMs: settings.runMaxWallSeconds * 1_000,
          telemetry: dependencies.telemetry,
          traceId: agentTraceId(request.headers),
          titleGenerator,
          titleSelection,
          selection,
          usageCapture,
        }),
      };
    },
    forwardHeaders: { allow: [RESEARCHER_ID_HEADER] },
    runner,
  });
  const runtimeHandler = createCopilotRuntimeHandler({
    activateChannels: false,
    basePath: "/api/agent/copilotkit",
    hooks: {
      onError: () => safeJsonResponse("AGENT_SERVICE_UNAVAILABLE", 503),
    },
    mode: "multi-route",
    runtime,
  });
  const turnControl = new MastraTurnControl(agent, runner, repository);
  let closePromise: Promise<void> | undefined;

  return {
    close: () => closePromise ??= (async () => {
      const interruptedRuns = await runner.shutdown();
      await Promise.all(pendingBridges);
      await Promise.all(interruptedRuns.map((runId) => repository.awaitFrameworkRunSettled(runId)));
      await titleGenerator.settled();
      await Promise.all([...memories.values()].map((memory) => memory.settled()));
      await repository.failInterruptedRunsAfterHostRestart();
      await storage.close();
      await readinessPool.end();
      await pool.end();
    })(),
    deleteSession: async (threadId, researcher) => {
      // Ownership must be checked before observable Runner state. A foreign
      // running Session must be indistinguishable from an unknown Session.
      await assertOwnedThread(repository, threadId, researcher.researcher_id);
      await runner.mutateSessionWhenIdle(
        threadId,
        () => repository.deleteSession(threadId, researcher.researcher_id),
      );
    },
    commandReceipt: (threadId, commandId, researcher) => repository.commandReceipt(
      threadId,
      researcher.researcher_id,
      commandId,
    ),
    handle: (request, researcher) => handleAuthenticatedRuntimeRequest({
      repository,
      request,
      researcher,
      runtimeHandler,
      settings,
    }),
    preference: async (threadId, researcher) => {
      if (!isChatThreadId(threadId)) return null;
      const preference = await repository.threadPreference(
        threadId,
        researcher.researcher_id,
      );
      return preference === null ? null : {
        model_key: preference.modelKey,
        reasoning_effort: preference.reasoningEffort,
      };
    },
    renameSession: (threadId, researcher, title, expectedVersion) => (
      repository.renameSession(
        threadId,
        researcher.researcher_id,
        title,
        expectedVersion,
      )
    ),
    ready: readiness,
    session: (threadId, researcher) => repository.session(
      threadId,
      researcher.researcher_id,
    ),
    sessions: (cursor, researcher) => repository.listSessions(
      researcher.researcher_id,
      cursor,
    ),
    steer: (threadId, researcher, input) => turnControl.steer(
      threadId,
      researcher.researcher_id,
      input,
    ),
    stop: (threadId, researcher, input) => turnControl.stop(
      threadId,
      researcher.researcher_id,
      input,
    ),
    timeline: (threadId, researcher, before, limit) => repository.timeline(
      threadId,
      researcher.researcher_id,
      before,
      limit,
    ),
  };
}

function createRunAgent(options: Readonly<{
  agentBuildRevision: string;
  mastra: Mastra;
  modelObservation: RunModelObservation;
  pendingBridges: Set<Promise<void>>;
  mcpRun: () => ReturnType<McpRunFactory>;
  providerModelId: string;
  repository: ResearchSessionRepository;
  requestContext: RequestContext;
  researcherId: string;
  run: ValidatedChatRun;
  runMaxWallMs: number;
  telemetry: AgentTelemetryWriter | undefined;
  traceId: string;
  titleGenerator: SessionTitleGenerator;
  titleSelection?: ResolvedModelSelection;
  selection: ResolvedModelSelection;
  usageCapture: RunUsageCapture;
}>): ResearchMastraAgent {
  const agent = options.mastra.getAgent(RESEARCH_AGENT_ID);
  if (agent === undefined) throw new Error("RESEARCH_AGENT_NOT_REGISTERED");
  options.requestContext.set("agentRunId", options.run.input.runId);
  options.requestContext.set("contextThreadId", options.run.input.threadId);
  options.requestContext.set("contextResearcherId", options.researcherId);
  const telemetry = createRunTelemetry({
    modelKey: options.selection.model.key,
    providerModelId: options.providerModelId,
    reasoningEffort: options.selection.effort,
    researcherId: options.researcherId,
    runId: options.run.input.runId,
    threadId: options.run.input.threadId,
    traceId: options.traceId,
  }, {
    metrics: () => ({ steps: options.modelObservation.steps, usage: options.usageCapture.value(),
      recoveryAttempts: options.modelObservation.recoveryAttempts,
      inputEstimate: options.modelObservation.inputEstimate,
      compaction: options.requestContext.get<string, SessionContextController | undefined>("sessionContextController")?.compactionStatistics }),
    write: options.telemetry,
  });
  options.modelObservation.onCallFinished = call => telemetry.modelCallFinished(call);
  return new ResearchMastraAgent({
    agent,
    agentId: RESEARCH_AGENT_ID,
    a2ui: researchA2UIBridgeConfig(),
    emitInterruptOutcome: true,
    // Keep private observation content inside the Host's Memory store.
    observationalMemory: false,
    requestContext: options.requestContext,
    resourceId: options.researcherId,
  }, {
    agentBuildRevision: options.agentBuildRevision,
    failure: () => options.modelObservation.terminalFailure(),
    mcpRun: options.mcpRun,
    pendingBridges: options.pendingBridges,
    providerModelId: options.providerModelId,
    repository: options.repository,
    requestContext: options.requestContext,
    researcherId: options.researcherId,
    run: options.run,
    runMaxWallMs: options.runMaxWallMs,
    metrics: () => ({
      generatedBytes: options.modelObservation.outputBytes,
      steps: options.modelObservation.steps,
    }),
    selection: {
      modelKey: options.selection.model.key,
      providerModelId: options.providerModelId,
      reasoningEffort: options.selection.effort,
    },
    telemetry,
    scheduleTitle: options.run.command === "prompt" && options.titleSelection !== undefined
      ? () => options.titleGenerator.schedule({
          languageModel: options.titleSelection!.languageModel,
          message: options.run.command === "prompt" ? options.run.userMessage.content : "",
          providerOptions: options.titleSelection!.providerOptions,
          researcherId: options.researcherId,
          threadId: options.run.input.threadId,
        })
      : undefined,
    usage: () => options.usageCapture.value(),
  });
}

function researchA2UIBridgeConfig() {
  return { injectA2UITool: false } as const;
}

async function handleAuthenticatedRuntimeRequest(options: Readonly<{
  repository: ResearchSessionRepository;
  request: Request;
  researcher: VerifiedResearcher;
  runtimeHandler: (request: Request) => Promise<Response>;
  settings: AgentSettings;
}>): Promise<Response> {
  try {
    const url = new URL(options.request.url);
    const pathname = url.pathname;
    const basePath = "/api/agent/copilotkit";
    const isRun = options.request.method === "POST"
      && pathname === `${basePath}/agent/${RESEARCH_AGENT_ID}/run`;
    const isConnect = options.request.method === "POST"
      && pathname === `${basePath}/agent/${RESEARCH_AGENT_ID}/connect`;
    const isInfo = options.request.method === "GET" && pathname === `${basePath}/info`;
    // The library also ships Stop, inspector, unscoped Thread and Memory
    // endpoints. None is a ThesisTrace Chat API or an alternate replay path.
    if (url.search !== "" || (!isRun && !isConnect && !isInfo)) {
      throw new SessionNotFoundError();
    }
    if (isRun) {
      const run = await readValidatedChatRun(options.request, options.settings.modelRegistry);
      if (run.command !== "prompt" || run.sessionMode === "existing") {
        await assertOwnedThread(options.repository, run.input.threadId, options.researcher.researcher_id);
      } else {
        await assertRunnableThread(options.repository, run.input.threadId, options.researcher.researcher_id);
      }
      // Answer has no new Turn identity on which the generic runtime can
      // report admission errors. Validate its exact suspended Turn and command
      // identity at the product boundary so stale/conflicting answers retain
      // the documented 409 contract. The durable mutation still occurs later
      // in prepareRun under the Session transaction.
      if (run.command === "answer") {
        await options.repository.runExecution(run, options.researcher.researcher_id);
      }
    } else if (isConnect) {
      const threadId = await readThreadId(options.request);
      await assertOwnedThread(
        options.repository,
        threadId,
        options.researcher.researcher_id,
      );
    }

    const headers = new Headers(options.request.headers);
    headers.set(RESEARCHER_ID_HEADER, options.researcher.researcher_id);
    const response = await options.runtimeHandler(
      new Request(options.request, { headers }),
    );
    return normalizeRuntimeResponse(response);
  } catch (error) {
    if (error instanceof ChatRequestError) {
      return safeJsonResponse(error.code, error.status);
    }
    if (error instanceof ChatControlError) {
      return safeJsonResponse(error.code, error.status);
    }
    if (error instanceof ChatRunConflictError) {
      return safeJsonResponse("CHAT_COMMAND_CONFLICT", 409);
    }
    if (error instanceof SessionActiveRunError) {
      return safeJsonResponse("CHAT_SESSION_RUN_ACTIVE", 409);
    }
    if (error instanceof SessionNotFoundError) {
      return safeJsonResponse("CHAT_SESSION_NOT_FOUND", 404);
    }
    return safeJsonResponse("AGENT_SERVICE_UNAVAILABLE", 503);
  }
}

function normalizeRuntimeResponse(response: Response): Response {
  if (response.body === null) return response;

  // CopilotKit's runtime stream can yield text chunks. A Fetch Response body
  // must yield bytes, so normalize once at the HTTP boundary before Hono or a
  // browser consumes it.
  const reader = (response.body as ReadableStream<unknown>).getReader();
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    async pull(controller) {
      try {
        const chunk = await reader.read();
        if (chunk.done) {
          controller.close();
          return;
        }
        if (typeof chunk.value === "string") {
          controller.enqueue(encoder.encode(chunk.value));
          return;
        }
        if (chunk.value instanceof Uint8Array) {
          controller.enqueue(chunk.value);
          return;
        }
        throw new Error("INVALID_RUNTIME_STREAM_CHUNK");
      } catch (error) {
        controller.error(error);
      }
    },
    async cancel(reason) {
      await reader.cancel(reason);
    },
  });
  return new Response(body, {
    headers: response.headers,
    status: response.status,
    statusText: response.statusText,
  });
}

async function assertRunnableThread(
  repository: ResearchSessionRepository,
  threadId: string,
  researcherId: string,
): Promise<void> {
  if (await repository.ownership(threadId, researcherId) === "foreign") {
    throw new SessionNotFoundError();
  }
}

async function assertOwnedThread(
  repository: ResearchSessionRepository,
  threadId: string,
  researcherId: string,
): Promise<void> {
  if (await repository.ownership(threadId, researcherId) !== "owned") {
    throw new SessionNotFoundError();
  }
}

function createRequestContext(
  selection: ResolvedModelSelection,
): RequestContext {
  const context = new RequestContext();
  context.set("selection", selection);
  context.set("mcpTools", {});
  return context;
}

function selectionFrom(context: RequestContext): ResolvedModelSelection {
  return context.get<string, ResolvedModelSelection>("selection");
}

function mcpToolsFrom(context: RequestContext): DiscoveredMcpTools {
  return context.get<string, DiscoveredMcpTools>("mcpTools");
}

function researchToolsFrom(context: RequestContext): DiscoveredMcpTools {
  const mcpTools = mcpToolsFrom(context);
  if (Object.hasOwn(mcpTools, RESEARCH_A2UI_TOOL_NAME) || Object.hasOwn(mcpTools, "ask_user")) {
    throw new Error("MCP_TOOL_NAME_RESERVED");
  }
  return Object.fromEntries(Object.entries({ ...mcpTools, ask_user: askUserTool,
    [RESEARCH_A2UI_TOOL_NAME]: researchA2UITool }).sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0));
}

function mcpRunFrom(context: RequestContext): import("./mcp-run.js").McpRun | undefined {
  return context.get<string, import("./mcp-run.js").McpRun | undefined>("mcpRun");
}

function researchAgentInstructions(context: RequestContext): string {
  return selectionFrom(context).model.providerAdapter === "scripted"
    ? `${RESEARCH_AGENT_INSTRUCTIONS}\nDeterministic privacy fixture: ${PRIVACY_CANARIES.system}.`
    : RESEARCH_AGENT_INSTRUCTIONS;
}

function safeJsonResponse(code: string, status: number): Response {
  return new Response(JSON.stringify({ code }), {
    headers: {
      "Cache-Control": "no-store",
      "Content-Type": "application/json",
    },
    status,
  });
}
