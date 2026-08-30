import { Agent } from "@mastra/core/agent";
import { ConsoleLogger } from "@mastra/core/logger";
import { Mastra } from "@mastra/core/mastra";
import { RequestContext } from "@mastra/core/request-context";
import { Memory } from "@mastra/memory";
import { PostgresStore } from "@mastra/pg";
import {
  CopilotRuntime,
  createCopilotRuntimeHandler,
} from "@copilotkit/runtime/v2";
import { MastraAgent } from "@ag-ui/mastra";

import {
  ChatRequestError,
  isChatThreadId,
  readThreadId,
  readValidatedChatRun,
  type ValidatedChatRun,
} from "./chat-request.js";
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
import {
  createMcpRunFactory,
  type DiscoveredMcpTools,
  type McpRunFactory,
} from "./mcp-run.js";
import { ResearchMastraAgent } from "./research-mastra-agent.js";
import { createAgentReadiness } from "./readiness.js";
import {
  ResearchSessionRepository,
  SessionNotFoundError,
  type RenamedSession,
  type SessionPage,
} from "./session-repository.js";
import type { SessionCursor } from "./session-management.js";
import { SessionTitleGenerator } from "./session-title.js";
import type { VerifiedResearcher } from "./session-verifier.js";
import { verifyAgentSchema } from "./schema-contract.js";
import { RunUsageCapture } from "./usage-capture.js";

const RESEARCH_AGENT_ID = "research";
const RESEARCH_AGENT_INSTRUCTIONS = `You are the ThesisTrace Research Agent.
Help a researcher turn an investment idea into a precise, testable Alpha research plan.
Use only the Tools supplied by the current authenticated MCP discovery. You own Tool selection, arguments, Folder choice, Formula authoring and correction, Research type, dates, universe, neutralization, Strategy parameters, polling decisions, Result-section selection, and the final response.
Use reliable platform defaults when the investment intent is clear. Ask a focused follow-up only when missing intent would materially change the Research; do not turn clear requests into a parameter wizard.
Treat Formula diagnostics and admission rejection as structured correctable results. Preserve stable authentication, authorization, lifecycle, transient, and internal Tool error meanings. Retry a transient Tool call only when appropriate, after its retry_after_seconds guidance, with the exact same arguments.
For every effectful Tool call, derive a caller-stable request_id from the current Agent Run identity plus an operation and revision. Reuse that exact request_id and command after an uncertain response; allocate a new revision only when a structured rejection requires a changed command.
State assumptions and distinguish proposals from persisted Research facts. Never claim that a ResearchRun or Result exists unless an authoritative Tool result confirms it. Once Research is admitted, remember that the Core Worker continues independently if this Agent Run ends.`;

export type ResearchRuntime = Readonly<{
  close: () => Promise<void>;
  deleteSession: (threadId: string, researcher: VerifiedResearcher) => Promise<void>;
  handle: (request: Request, researcher: VerifiedResearcher) => Promise<Response>;
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
}>;
export type ResearchRuntimeDependencies = Readonly<{
  mcpRunFactory?: McpRunFactory;
  readinessFetch?: typeof globalThis.fetch;
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
  const memory = new Memory({
    options: {
      lastMessages: 50,
      observationalMemory: false,
      semanticRecall: false,
      workingMemory: { enabled: false },
    },
    storage,
    vector: false,
  });
  const agent = new Agent({
    defaultOptions: ({ requestContext }) => ({
      maxSteps: 16,
      providerOptions: selectionFrom(requestContext).providerOptions,
      // A transport/protocol failure is converted into one safe Tool result so
      // AG-UI can close that exact invocation. Stop before another provider
      // step; ResearchMastraAgent will persist the failed product Run.
      stopWhen: () => mcpRunFrom(requestContext)?.hasFatalToolFailure() === true,
    }),
    id: RESEARCH_AGENT_ID,
    instructions: ({ requestContext }) => researchAgentInstructions(requestContext),
    maxRetries: 0,
    memory,
    model: ({ requestContext }) => selectionFrom(requestContext).languageModel,
    name: "ThesisTrace Research Agent",
    tools: ({ requestContext }) => mcpToolsFrom(requestContext),
  });
  const mastra = new Mastra({
    agents: { [RESEARCH_AGENT_ID]: agent },
    logger: new ConsoleLogger({
      level: "info",
      // Provider errors can contain prompts, response bodies, or credentials.
      // The product run row and safe AG-UI error remain the operator/client
      // boundary; never emit Mastra's raw provider error object.
      filter: ({ message }) => message !== "Error in agent stream"
        && message !== "Upstream LLM API error",
    }),
    recovery: { durableAgents: "off" },
    storage,
  });
  const runner = new DurableResearchAgentRunner(repository);
  const runtime = new CopilotRuntime({
    agents: async ({ request }) => {
      const researcherId = request.headers.get(RESEARCHER_ID_HEADER);
      if (researcherId === null) throw new SessionNotFoundError();

      const isRun = new URL(request.url).pathname.endsWith(
        `/agent/${RESEARCH_AGENT_ID}/run`,
      );
      const validated = isRun
        ? await readValidatedChatRun(request, settings.modelRegistry)
        : undefined;
      const usageCapture = validated === undefined ? undefined : new RunUsageCapture();
      const selection = validated === undefined
        ? modelRuntime.resolve(
            settings.modelRegistry.defaultModelKey,
            settings.modelRegistry.models.find(
              (candidate) => candidate.key === settings.modelRegistry.defaultModelKey,
            )?.defaultReasoningEffort ?? "medium",
          )
        : modelRuntime.resolve(
            validated.modelKey,
            validated.reasoningEffort,
            usageCapture,
          );
      const titleSelection = validated === undefined
        ? undefined
        : modelRuntime.resolve(validated.modelKey, validated.reasoningEffort);
      const requestContext = createRequestContext(selection);

      if (validated === undefined) {
        return {
          [RESEARCH_AGENT_ID]: new MastraAgent({
            agent,
            agentId: RESEARCH_AGENT_ID,
            a2ui: { injectA2UITool: false },
            emitInterruptOutcome: true,
            observationalMemory: false,
            requestContext,
            resourceId: researcherId,
          }),
        };
      }
      if (usageCapture === undefined) {
        throw new Error("RUN_USAGE_CAPTURE_NOT_CREATED");
      }
      if (titleSelection === undefined) {
        throw new Error("TITLE_MODEL_SELECTION_NOT_CREATED");
      }

      return {
        [RESEARCH_AGENT_ID]: createRunAgent({
          agentBuildRevision: settings.agentBuildRevision,
          mastra,
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
          titleGenerator,
          titleSelection,
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

  return {
    close: async () => {
      await titleGenerator.settled();
      await memory.settled();
      await storage.close();
      await readinessPool.end();
      await pool.end();
    },
    deleteSession: (threadId, researcher) => runner.mutateSessionWhenIdle(
      threadId,
      () => repository.deleteSession(threadId, researcher.researcher_id),
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
  };
}

function createRunAgent(options: Readonly<{
  agentBuildRevision: string;
  mastra: Mastra;
  mcpRun: () => ReturnType<McpRunFactory>;
  providerModelId: string;
  repository: ResearchSessionRepository;
  requestContext: RequestContext;
  researcherId: string;
  run: ValidatedChatRun;
  runMaxWallMs: number;
  titleGenerator: SessionTitleGenerator;
  titleSelection: ResolvedModelSelection;
  usageCapture: RunUsageCapture;
}>): ResearchMastraAgent {
  const agent = options.mastra.getAgent(RESEARCH_AGENT_ID);
  if (agent === undefined) throw new Error("RESEARCH_AGENT_NOT_REGISTERED");
  options.requestContext.set("agentRunId", options.run.input.runId);
  return new ResearchMastraAgent({
    agent,
    agentId: RESEARCH_AGENT_ID,
    a2ui: { injectA2UITool: false },
    emitInterruptOutcome: true,
    observationalMemory: false,
    requestContext: options.requestContext,
    resourceId: options.researcherId,
  }, {
    agentBuildRevision: options.agentBuildRevision,
    mcpRun: options.mcpRun,
    providerModelId: options.providerModelId,
    repository: options.repository,
    requestContext: options.requestContext,
    researcherId: options.researcherId,
    run: options.run,
    runMaxWallMs: options.runMaxWallMs,
    scheduleTitle: () => options.titleGenerator.schedule({
      languageModel: options.titleSelection.languageModel,
      message: options.run.latestUserMessage.content,
      providerOptions: options.titleSelection.providerOptions,
      researcherId: options.researcherId,
      threadId: options.run.input.threadId,
    }),
    usage: () => options.usageCapture.value(),
  });
}

async function handleAuthenticatedRuntimeRequest(options: Readonly<{
  repository: ResearchSessionRepository;
  request: Request;
  researcher: VerifiedResearcher;
  runtimeHandler: (request: Request) => Promise<Response>;
  settings: AgentSettings;
}>): Promise<Response> {
  try {
    const pathname = new URL(options.request.url).pathname;
    if (pathname.endsWith(`/agent/${RESEARCH_AGENT_ID}/run`)) {
      const run = await readValidatedChatRun(options.request, options.settings.modelRegistry);
      await assertRunnableThread(
        options.repository,
        run.input.threadId,
        options.researcher.researcher_id,
      );
    } else if (pathname.endsWith(`/agent/${RESEARCH_AGENT_ID}/connect`)) {
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

function mcpRunFrom(context: RequestContext): import("./mcp-run.js").McpRun | undefined {
  return context.get<string, import("./mcp-run.js").McpRun | undefined>("mcpRun");
}

function researchAgentInstructions(context: RequestContext): string {
  const agentRunId = context.get<string, string | undefined>("agentRunId");
  return agentRunId === undefined
    ? RESEARCH_AGENT_INSTRUCTIONS
    : `${RESEARCH_AGENT_INSTRUCTIONS}\nAgent Run identity: ${agentRunId}.`;
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
