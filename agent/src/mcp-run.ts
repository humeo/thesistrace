import { noopLogger } from "@mastra/core/logger";
import type { Tool } from "@mastra/core/tools";
import { getMcpCallToolMeta, MCPClient } from "@mastra/mcp";

import type { AgentSettings } from "./config.js";
import { toolFailureCode, type AgentFailureCode } from "../../contracts/agent-failure.mjs";
import { AGENT_LIMITS } from "./guarded-language-model.js";
import {
  createMcpTokenExchanger,
  McpRunPreparationError,
} from "./mcp-token-exchanger.js";
import {
  DURABLE_TOOL_FAILURE,
  DURABLE_TOOL_OUTCOME_FIELD,
} from "./tool-outcome.js";

const MCP_CONNECT_TIMEOUT_MS = 2_000;
const MCP_DISCOVERY_TIMEOUT_MS = 5_000;
const MCP_SERVER_ID = "thesistrace";
const MCP_TOOL_OUTCOME_META_KEY = "thesistrace/tool-outcome";

export type DiscoveredMcpTools = Record<string, Tool<any, any, any, any>>;
export type McpToolFailure = Readonly<{ code: AgentFailureCode; fatal: boolean }>;
export type McpRun = Readonly<{
  close: () => Promise<void>;
  hasFatalToolFailure: () => boolean;
  toolFailure: (toolCallId: string) => McpToolFailure | undefined;
  tools: DiscoveredMcpTools;
}>;
export type McpRunFactory = (
  headers: Headers,
  runId: string,
) => Promise<McpRun>;
type McpClientLike = Pick<
  MCPClient,
  "__setLogger" | "disconnect" | "listToolsetsWithErrors"
>;

export function createMcpRunFactory(
  settings: AgentSettings,
  dependencies: Readonly<{
    fetch?: typeof globalThis.fetch;
    mcpClient?: (
      options: ConstructorParameters<typeof MCPClient>[0],
    ) => McpClientLike;
  }> = {},
): McpRunFactory {
  const exchange = createMcpTokenExchanger({
    authInternalOrigin: settings.authInternalOrigin,
    clockSkewSeconds: settings.mcpClockSkewSeconds,
    fetch: dependencies.fetch,
    runMaxWallSeconds: settings.runMaxWallSeconds,
  });
  const createClient = dependencies.mcpClient ?? ((options) => new MCPClient(options));
  const mcpUrl = new URL(settings.mcpInternalUrl);

  return async (headers, runId) => {
    const exchanged = await exchange(headers);
    const client = createClient({
      id: `thesistrace-agent-run-${runId}`,
      servers: {
        [MCP_SERVER_ID]: {
          allowedHosts: [mcpUrl.host],
          connectTimeout: MCP_CONNECT_TIMEOUT_MS,
          enableServerLogs: false,
          forwardInstructions: false,
          // Core business rejections are ordinary MCP results that the model
          // must be able to inspect and act on. Transport/protocol failures
          // still reject from the MCP client and are tracked below as fatal.
          onToolError: "return",
          protocolVersion: "2026-07-28",
          requestInit: {
            headers: { Authorization: `${exchanged.token_type} ${exchanged.access_token}` },
            redirect: "error",
          },
          url: mcpUrl,
        },
      },
      timeout: settings.runMaxWallSeconds * 1_000,
    });
    // @mastra/mcp includes Tool arguments in its error logger. Core already
    // owns safe Tool observability, so this per-Run client must remain silent.
    client.__setLogger(noopLogger);
    let closed = false;
    const close = async () => {
      if (closed) return;
      closed = true;
      await client.disconnect();
    };
    try {
      const discovery = await client.listToolsetsWithErrors({
        perServerTimeoutMs: MCP_DISCOVERY_TIMEOUT_MS,
      });
      const toolsets = Object.entries(discovery.toolsets);
      if (
        Object.keys(discovery.errors).length !== 0
        || Object.keys(discovery.errorDetails).length !== 0
        || toolsets.length !== 1
        || toolsets[0]?.[0] !== MCP_SERVER_ID
        || Object.keys(toolsets[0][1]).length === 0
      ) {
        const status = discovery.errorDetails[MCP_SERVER_ID]?.httpStatus;
        throw new McpRunPreparationError(status === 401 || status === 403 ? "MCP_AUTHENTICATION" : "MCP_TRANSIENT");
      }
      const tracked = trackToolFailures(toolsets[0][1]);
      return {
        close,
        hasFatalToolFailure: tracked.hasFatalToolFailure,
        toolFailure: tracked.toolFailure,
        tools: tracked.tools,
      };
    } catch (error) {
      await close().catch(() => undefined);
      throw error instanceof McpRunPreparationError ? error : new McpRunPreparationError(mcpTransportFailureCode(error));
    }
  };
}

function trackToolFailures(tools: DiscoveredMcpTools): Readonly<{
  hasFatalToolFailure: () => boolean;
  toolFailure: (toolCallId: string) => McpToolFailure | undefined;
  tools: DiscoveredMcpTools;
}> {
  const failures = new Map<string, McpToolFailure>();
  const tracked = Object.fromEntries(Object.entries(tools).map(([name, tool]) => {
    const execute = tool.execute;
    if (execute === undefined) throw new McpRunPreparationError();
    const wrapped = new Proxy(tool, {
      get(target, property, receiver) {
        if (property !== "execute") return Reflect.get(target, property, receiver);
        return async (...args: unknown[]) => {
          const toolCallId = requiredToolCallId(args[1]);
          try {
            const result = await Reflect.apply(execute, target, args);
            if (Buffer.byteLength(JSON.stringify(result), "utf8") > AGENT_LIMITS.toolResultBytes) {
              failures.set(toolCallId, { code: "AGENT_LIMIT", fatal: true });
              return safeFatalToolResult("AGENT_LIMIT");
            }
            const outcome = readMcpToolOutcome(result);
            if (outcome === "failed") {
              const code = coreToolFailureCode(result);
              failures.set(toolCallId, { code, fatal: code === "MCP_AUTHENTICATION" });
              return markDurableToolFailure(result);
            }
            if (outcome === "succeeded") return result;
            // ThesisTrace Core is the sole MCP server and marks every Tool
            // result. A missing or malformed marker is a protocol failure, not
            // a successful business result that may continue the model loop.
            failures.set(toolCallId, { code: "MCP_TRANSIENT", fatal: true });
            return safeFatalToolResult("MCP_TRANSIENT");
          } catch (error) {
            const code = mcpTransportFailureCode(error);
            failures.set(toolCallId, { code, fatal: true });
            // AI SDK emits a tool-error chunk for a rejected execute call, but
            // the AG-UI adapter does not emit a corresponding TOOL_CALL_RESULT.
            // Resolve one safe internal MCP-shaped error so the adapter emits
            // the terminal Tool result that ResearchMastraAgent can durably
            // fail on. Raw transport/protocol details never reach the model.
            return safeFatalToolResult(code);
          }
        };
      },
    });
    return [name, wrapped];
  })) as DiscoveredMcpTools;
  return {
    hasFatalToolFailure: () => (
      [...failures.values()].some((failure) => failure.fatal)
    ),
    toolFailure: (toolCallId) => failures.get(toolCallId),
    tools: tracked,
  };
}

function safeFatalToolResult(code: AgentFailureCode) {
  return {
    [DURABLE_TOOL_OUTCOME_FIELD]: DURABLE_TOOL_FAILURE,
    code,
    content: [{ text: JSON.stringify({ code }), type: "text" as const }],
    isError: true,
  };
}

function coreToolFailureCode(result: unknown): AgentFailureCode {
  const code = result !== null && typeof result === "object" && "code" in result ? result.code : undefined;
  return toolFailureCode(code);
}

/** The MCP SDK may wrap HTTP errors; inspect bounded typed status fields only. */
function mcpTransportFailureCode(error: unknown): AgentFailureCode {
  const seen = new Set<unknown>();
  for (let depth = 0; depth < 8 && error !== null && typeof error === "object" && !seen.has(error); depth++) {
    seen.add(error);
    const status = "status" in error ? error.status : "statusCode" in error ? error.statusCode : undefined;
    if (status === 401 || status === 403) return "MCP_AUTHENTICATION";
    error = "cause" in error ? error.cause : undefined;
  }
  return "MCP_TRANSIENT";
}

function markDurableToolFailure<T>(result: T): T {
  if (result === null || typeof result !== "object") {
    throw new Error("MCP_TOOL_FAILURE_RESULT_INVALID");
  }
  Object.defineProperty(result, DURABLE_TOOL_OUTCOME_FIELD, {
    configurable: false,
    enumerable: true,
    value: DURABLE_TOOL_FAILURE,
    writable: false,
  });
  return result;
}

function requiredToolCallId(options: unknown): string {
  if (
    options === null
    || typeof options !== "object"
    || !("agent" in options)
    || options.agent === null
    || typeof options.agent !== "object"
    || !("toolCallId" in options.agent)
    || typeof options.agent.toolCallId !== "string"
    || options.agent.toolCallId.length === 0
  ) {
    throw new Error("MCP_TOOL_CALL_CONTEXT_INVALID");
  }
  return options.agent.toolCallId;
}

function readMcpToolOutcome(output: unknown): "failed" | "succeeded" | undefined {
  const attached = getMcpCallToolMeta(output);
  const direct = output !== null
    && typeof output === "object"
    && "_meta" in output
    && output._meta !== null
    && typeof output._meta === "object"
    ? output._meta as Record<string, unknown>
    : undefined;
  const outcome = (attached ?? direct)?.[MCP_TOOL_OUTCOME_META_KEY];
  return outcome === "failed" || outcome === "succeeded" ? outcome : undefined;
}
