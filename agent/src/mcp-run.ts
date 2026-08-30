import { noopLogger } from "@mastra/core/logger";
import type { Tool } from "@mastra/core/tools";
import { getMcpCallToolMeta, MCPClient } from "@mastra/mcp";

import type { AgentSettings } from "./config.js";
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
const SAFE_TRANSPORT_FAILURE = Object.freeze({
  [DURABLE_TOOL_OUTCOME_FIELD]: DURABLE_TOOL_FAILURE,
  content: [{
    text: JSON.stringify({ code: "MCP_TRANSPORT_UNAVAILABLE" }),
    type: "text" as const,
  }],
  isError: true,
});

export type DiscoveredMcpTools = Record<string, Tool<any, any, any, any>>;
export type McpToolFailure = "business" | "transport";
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
        throw new McpRunPreparationError();
      }
      const tracked = trackToolFailures(toolsets[0][1]);
      return {
        close,
        hasFatalToolFailure: tracked.hasFatalToolFailure,
        toolFailure: tracked.toolFailure,
        tools: tracked.tools,
      };
    } catch {
      await close().catch(() => undefined);
      throw new McpRunPreparationError();
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
            const outcome = readMcpToolOutcome(result);
            if (outcome === "failed") {
              failures.set(toolCallId, "business");
              return markDurableToolFailure(result);
            }
            if (outcome === "succeeded") return result;
            // ThesisTrace Core is the sole MCP server and marks every Tool
            // result. A missing or malformed marker is a protocol failure, not
            // a successful business result that may continue the model loop.
            failures.set(toolCallId, "transport");
            return SAFE_TRANSPORT_FAILURE;
          } catch {
            failures.set(toolCallId, "transport");
            // AI SDK emits a tool-error chunk for a rejected execute call, but
            // the AG-UI adapter does not emit a corresponding TOOL_CALL_RESULT.
            // Resolve one safe internal MCP-shaped error so the adapter emits
            // the terminal Tool result that ResearchMastraAgent can durably
            // fail on. Raw transport/protocol details never reach the model.
            return SAFE_TRANSPORT_FAILURE;
          }
        };
      },
    });
    return [name, wrapped];
  })) as DiscoveredMcpTools;
  return {
    hasFatalToolFailure: () => (
      [...failures.values()].some((failure) => failure === "transport")
    ),
    toolFailure: (toolCallId) => failures.get(toolCallId),
    tools: tracked,
  };
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
