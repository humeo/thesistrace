import type { Tool } from "@mastra/core/tools";
import {
  MCP_CALL_TOOL_CONTENT,
  MCP_CALL_TOOL_META,
  type MCPClient,
} from "@mastra/mcp";
import { describe, expect, it, vi } from "vitest";

import type { AgentSettings } from "./config.js";
import { createMcpRunFactory } from "./mcp-run.js";
import { AGENT_LIMITS } from "./guarded-language-model.js";
import {
  DURABLE_TOOL_FAILURE,
  DURABLE_TOOL_OUTCOME_FIELD,
} from "./tool-outcome.js";

const settings = {
  authInternalOrigin: "http://auth:8200",
  mcpClockSkewSeconds: 30,
  mcpInternalUrl: "http://api:8100/mcp",
  runMaxWallSeconds: 300,
} as AgentSettings;
const TOOL_OUTCOME_META_KEY = "thesistrace/tool-outcome";
const discoveredTools = {
  first_discovered_tool: {
    description: "First discovered Tool",
    execute: async () => adaptedCoreResult({
      content: [{ text: JSON.stringify({ status: "ok" }), type: "text" }],
      isError: false,
      structuredContent: { status: "ok" },
      _meta: { [TOOL_OUTCOME_META_KEY]: "succeeded" },
    }),
    id: "first_discovered_tool",
  } as Tool<any, any, any, any>,
  second_discovered_tool: {
    description: "Second discovered Tool",
    execute: async () => {
      throw new Error("raw MCP failure with arguments-canary");
    },
    id: "second_discovered_tool",
  } as Tool<any, any, any, any>,
  structured_error_tool: {
    description: "Structured Core rejection",
    execute: async () => adaptedCoreResult({
      content: [{
        text: JSON.stringify({
          code: "TEMPORARILY_UNAVAILABLE",
          retry_after_seconds: 3,
          retryable: true,
        }),
        type: "text",
      }],
      _meta: { [TOOL_OUTCOME_META_KEY]: "failed" },
      isError: true,
      structuredContent: {
        code: "TEMPORARILY_UNAVAILABLE",
        retry_after_seconds: 3,
        retryable: true,
      },
    }),
    id: "structured_error_tool",
  } as Tool<any, any, any, any>,
};

describe("per-Run MCP lifecycle", () => {
  it("preserves MCP HTTP authentication without exposing the raw transport exception", async () => {
    const run = await fixtureRun(async () => { throw new Error("private transport", { cause: Object.assign(new Error("private cause"), { status: 403 }) }); });
    const result = await run.tools.fixture.execute?.({}, toolOptions("auth"));
    expect(run.toolFailure("auth")).toEqual({ code: "MCP_AUTHENTICATION", fatal: true });
    expect(JSON.stringify(result)).not.toContain("private");
  });

  it.each([
    ["INVALID_INPUT", "TOOL_REJECTION", false],
    ["FORBIDDEN", "MCP_AUTHENTICATION", true],
    ["TEMPORARILY_UNAVAILABLE", "MCP_TRANSIENT", false],
    ["INTERNAL", "TOOL_ERROR", false],
  ])("classifies %s without a Host retry or losing Core guidance", async (code, category, fatal) => {
    const result = adaptedCoreResult({ _meta: { [TOOL_OUTCOME_META_KEY]: "failed" },
      content: [], isError: true, structuredContent: { code, retry_after_seconds: 3 } });
    const execute = vi.fn(async () => result);
    const run = await fixtureRun(execute);
    await expect(run.tools.fixture.execute?.({}, toolOptions("call"))).resolves.toMatchObject({ code, retry_after_seconds: 3 });
    expect(run.toolFailure("call")).toEqual({ code: category, fatal });
    expect(run.hasFatalToolFailure()).toBe(fatal);
    expect(execute).toHaveBeenCalledOnce();
  });

  it("rejects an oversized Tool result before the model or Memory receives it", async () => {
    const run = await fixtureRun(async () => adaptedCoreResult({
      _meta: { [TOOL_OUTCOME_META_KEY]: "succeeded" }, content: [], isError: false,
      structuredContent: { private: "x".repeat(AGENT_LIMITS.toolResultBytes + 1) },
    }));
    const result = await run.tools.fixture.execute?.({}, toolOptions("large"));
    expect(run.toolFailure("large")).toEqual({ code: "AGENT_LIMIT", fatal: true });
    expect(JSON.stringify(result).length).toBeLessThan(512);
    expect(JSON.stringify(result)).not.toContain("private");
  });

  it("pins the modern protocol and tracks failures for every discovered Core Tool", async () => {
    let clientOptions: Record<string, unknown> | undefined;
    const disconnect = vi.fn(async () => undefined);
    const setLogger = vi.fn();
    const create = createMcpRunFactory(settings, {
      fetch: async () => Response.json({
        access_token: "opaque-access-token",
        expires_in: 360,
        token_type: "Bearer",
      }),
      mcpClient: (options) => {
        clientOptions = options as unknown as Record<string, unknown>;
        return {
          __setLogger: setLogger,
          disconnect,
          listToolsetsWithErrors: async () => ({
            errorDetails: {},
            errors: {},
            toolsets: { thesistrace: discoveredTools },
          }),
        };
      },
    });

    const run = await create(new Headers({ cookie: "session-cookie" }), "run-id");
    expect(Object.keys(run.tools)).toEqual(Object.keys(discoveredTools));
    expect(run.tools.first_discovered_tool).not.toBe(
      discoveredTools.first_discovered_tool,
    );
    await expect(run.tools.first_discovered_tool.execute?.(
      {},
      toolOptions("first-call"),
    )).resolves
      .toEqual({ status: "ok" });
    expect(run.toolFailure("first-call")).toBeUndefined();
    expect(run.hasFatalToolFailure()).toBe(false);
    await expect(
      run.tools.structured_error_tool.execute?.(
        {},
        toolOptions("business-call"),
      ),
    ).resolves.toEqual({
      [DURABLE_TOOL_OUTCOME_FIELD]: DURABLE_TOOL_FAILURE,
      code: "TEMPORARILY_UNAVAILABLE",
      retry_after_seconds: 3,
      retryable: true,
    });
    expect(run.toolFailure("business-call")).toEqual({ code: "MCP_TRANSIENT", fatal: false });
    expect(run.hasFatalToolFailure()).toBe(false);
    await expect(
      run.tools.second_discovered_tool.execute?.(
        {},
        toolOptions("transport-call"),
      ),
    ).resolves.toEqual({
      [DURABLE_TOOL_OUTCOME_FIELD]: DURABLE_TOOL_FAILURE,
      code: "MCP_TRANSIENT",
      content: [{
        text: JSON.stringify({ code: "MCP_TRANSIENT" }),
        type: "text",
      }],
      isError: true,
    });
    expect(run.toolFailure("transport-call")).toEqual({ code: "MCP_TRANSIENT", fatal: true });
    expect(run.hasFatalToolFailure()).toBe(true);
    expect(setLogger).toHaveBeenCalledOnce();
    const servers = clientOptions?.servers as Record<string, Record<string, unknown>>;
    expect(servers.thesistrace).toMatchObject({
      allowedHosts: ["api:8100"],
      connectTimeout: 2_000,
      enableServerLogs: false,
      forwardInstructions: false,
      onToolError: "return",
      protocolVersion: "2026-07-28",
      url: new URL("http://api:8100/mcp"),
    });
    expect(new Headers(
      (servers.thesistrace.requestInit as RequestInit).headers,
    ).get("authorization")).toBe("Bearer opaque-access-token");
    await run.close();
    await run.close();
    expect(disconnect).toHaveBeenCalledOnce();
  });

  it("keeps concurrent success and transport failure state isolated by Tool call id", async () => {
    const releaseSuccess = deferred<void>();
    const releaseFailure = deferred<void>();
    const create = createMcpRunFactory(settings, {
      fetch: async () => Response.json({
        access_token: "opaque-access-token",
        expires_in: 360,
        token_type: "Bearer",
      }),
      mcpClient: () => ({
        __setLogger: vi.fn(),
        disconnect: vi.fn(async () => undefined),
        listToolsetsWithErrors: async () => ({
          errorDetails: {},
          errors: {},
          toolsets: {
            thesistrace: {
              successful: {
                description: "Successful concurrent Tool",
                id: "successful",
                execute: async () => {
                  await releaseSuccess.promise;
                  return adaptedCoreResult({
                    content: [{ text: "ok", type: "text" }],
                    isError: false,
                    structuredContent: { status: "ok" },
                    _meta: { [TOOL_OUTCOME_META_KEY]: "succeeded" },
                  });
                },
              } as Tool<any, any, any, any>,
              unavailable: {
                description: "Failed concurrent Tool",
                id: "unavailable",
                execute: async () => {
                  await releaseFailure.promise;
                  throw new Error("private parallel transport detail");
                },
              } as Tool<any, any, any, any>,
            },
          },
        }),
      }),
    });
    const run = await create(new Headers(), "parallel-run");
    const successful = run.tools.successful.execute?.(
      {},
      toolOptions("successful-call"),
    );
    const unavailable = run.tools.unavailable.execute?.(
      {},
      toolOptions("failed-call"),
    );

    releaseFailure.resolve();
    await expect(unavailable).resolves.toMatchObject({ isError: true });
    expect(run.toolFailure("successful-call")).toBeUndefined();
    expect(run.toolFailure("failed-call")).toEqual({ code: "MCP_TRANSIENT", fatal: true });
    releaseSuccess.resolve();
    await expect(successful).resolves.toEqual({ status: "ok" });

    expect(run.toolFailure("successful-call")).toBeUndefined();
    expect(run.toolFailure("failed-call")).toEqual({ code: "MCP_TRANSIENT", fatal: true });
  });

  it("rejects partial or empty discovery and disconnects the client", async () => {
    const discoveries: Array<Awaited<
      ReturnType<MCPClient["listToolsetsWithErrors"]>
    >> = [
      {
        errorDetails: {},
        errors: { thesistrace: "safe failure" },
        toolsets: {},
      },
      { errorDetails: {}, errors: {}, toolsets: { thesistrace: {} } },
      { errorDetails: {}, errors: {}, toolsets: {} },
    ];
    for (const discovery of discoveries) {
      const disconnect = vi.fn(async () => undefined);
      const create = createMcpRunFactory(settings, {
        fetch: async () => Response.json({
          access_token: "opaque-access-token",
          expires_in: 360,
          token_type: "Bearer",
        }),
        mcpClient: () => ({
          __setLogger: vi.fn(),
          disconnect,
          listToolsetsWithErrors: async () => discovery,
        }),
      });
      await expect(create(new Headers(), "run-id")).rejects.toThrow(
        "MCP_TRANSIENT",
      );
      expect(disconnect).toHaveBeenCalledOnce();
    }
  });
});

async function fixtureRun(execute: () => Promise<unknown>) {
  return createMcpRunFactory(settings, {
    fetch: async () => Response.json({ access_token: "fixture-token", expires_in: 360, token_type: "Bearer" }),
    mcpClient: () => ({ __setLogger: vi.fn(), disconnect: async () => undefined,
      listToolsetsWithErrors: async () => ({ errors: {}, errorDetails: {}, toolsets: {
        thesistrace: { fixture: { id: "fixture", description: "Fixture Tool", execute } as Tool<any, any, any, any> },
      } }),
    }),
  })(new Headers(), "fixture-run");
}

type RawCoreResult = Readonly<{
  _meta: Record<string, unknown>;
  content: readonly unknown[];
  isError: boolean;
  structuredContent: Record<string, unknown>;
}>;

function adaptedCoreResult(result: RawCoreResult): Record<string, unknown> {
  const output = { ...result.structuredContent };
  Object.defineProperties(output, {
    [MCP_CALL_TOOL_CONTENT]: { value: result.content },
    [MCP_CALL_TOOL_META]: { value: result._meta },
  });
  return output;
}

function toolOptions(toolCallId: string): never {
  return { agent: { messages: [], toolCallId } } as never;
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((selected) => {
    resolve = selected;
  });
  return { promise, resolve };
}
