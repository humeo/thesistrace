import { fileURLToPath } from "node:url";
import { createOpenAI } from "@ai-sdk/openai";
import { Agent } from "@mastra/core/agent";
import { noopLogger } from "@mastra/core/logger";
import { MCPClient } from "@mastra/mcp";
import { expect, it } from "vitest";

import type { AgentSettings } from "./config.js";
import { AGENT_LIMITS } from "./guarded-language-model.js";
import { createMcpRunFactory } from "./mcp-run.js";
import { McpSchemaValidator } from "./mcp-schema-validator.js";
import { openAIToolProvider } from "../test-fixtures/openai-tool-provider.js";

it("consumes Core instructions, recoverable rejections and bounded Result pages through the real SDKs", async () => {
  const core = fileURLToPath(new URL("../../core/", import.meta.url));
  const factory = createMcpRunFactory({
    authInternalOrigin: "http://auth.fixture", mcpClockSkewSeconds: 30,
    mcpInternalUrl: "http://core.fixture/mcp", runMaxWallSeconds: 30,
  } as AgentSettings, {
    fetch: async () => Response.json({ access_token: "fixture", token_type: "Bearer", expires_in: 360 }),
    mcpClient: options => {
      const server = options.servers.thesistrace;
      const client = new MCPClient({ ...options, servers: { thesistrace: {
        command: "uv", args: ["run", "--project", core, "--no-sync", "python",
          `${core}tests/architecture/research_agent_stdio_fixture.py`],
        forwardInstructions: server.forwardInstructions,
        instructionsMaxLength: server.instructionsMaxLength,
        onToolError: server.onToolError,
        protocolVersion: server.protocolVersion,
        jsonSchemaValidator: server.jsonSchemaValidator,
      } } });
      // This fixture boots a Python process; production connects to an already
      // running HTTP service. Keep cold-start time outside its discovery budget.
      return {
        __setLogger: logger => client.__setLogger(logger),
        disconnect: () => client.disconnect(),
        listToolsetsWithErrors: discovery => client.listToolsetsWithErrors({
          ...discovery, perServerTimeoutMs: 20_000,
        }),
      };
    },
  });
  const run = await factory(new Headers(), "core-contract");
  const options = (toolCallId: string) => ({ agent: { toolCallId } } as never);
  try {
    const submit = run.tools.submit_research_run;
    const result = run.tools.get_daily_track_result;
    expect(submit).toBeDefined();
    expect(result).toBeDefined();
    expect(submit.mcpMetadata).toMatchObject({
      forwardInstructions: true, instructionsMaxLength: 4096,
    });
    expect(submit.mcpMetadata?.serverInstructions).toContain("QAgentis");
    expect(submit.mcpMetadata?.serverInstructions).toContain("request_id");
    expect(submit.mcpMetadata?.serverInstructions).toContain("result_page");
    const provider = openAIToolProvider([]);
    const agent = new Agent({
      id: "core-schema", name: "Core schema", instructions: "Use the available research tools.",
      model: createOpenAI({ apiKey: "fixture-only", fetch: provider.fetch })("gpt-6.1-sol"),
      tools: run.tools, maxRetries: 0,
    });
    agent.__setLogger(noopLogger);
    const stream = await agent.stream("Describe the research workflow.", { maxSteps: 2 });
    await stream.consumeStream();
    const request = provider.requests[0];
    expect(JSON.stringify(request?.input)).toContain(submit.mcpMetadata?.serverInstructions);
    const schema = request?.tools?.find((tool) => tool.name === "submit_research_run")?.parameters;
    expect(schema).toBeDefined();
    const validate = new McpSchemaValidator().getValidator(JSON.parse(JSON.stringify(schema)));
    const framework = {
      request_id: "framework", folder_id: "folder_default", research_kind: "strategy_backtest",
      start_date: "2024-01-02", end_date: "2024-01-31", universe: "top300",
      formula: "close", neutralization: "none", initial_cash_cny: "100000",
      holdings_count: 10, selection_every_sessions: 5,
    };
    expect(validate(framework).valid).toBe(true);
    const { holdings_count: _holdings, ...missing } = framework;
    expect(validate(missing).valid).toBe(false);
    expect(validate({ ...framework, holdings_count: null }).valid).toBe(false);
    const batchSchema = request?.tools?.find((tool) => tool.name === "submit_research_batch")?.parameters;
    expect(batchSchema).toBeDefined();
    const validateBatch = new McpSchemaValidator().getValidator(JSON.parse(JSON.stringify(batchSchema)));
    const batch = {
      request_id: "batch", batch_kind: "strategy_sweep", start_date: "2024-01-02",
      end_date: "2024-01-31", universe: "top300", neutralization: "none",
      alpha: { formula: "close" }, strategies: [{
        item_key: "candidate", initial_cash_cny: "100000", holdings_count: 10,
        selection_every_sessions: 5,
      }],
    };
    expect(validateBatch(batch).valid).toBe(true);
    expect(validateBatch({ ...batch, alpha: null }).valid).toBe(false);
    const independent = {
      request_id: "independent", batch_kind: "independent_strategies",
      start_date: batch.start_date, end_date: batch.end_date, universe: batch.universe,
      strategies: [
        { ...batch.strategies[0], formula: "close", neutralization: "industry" },
        { item_key: "direct", strategy_mode: "direct", initial_cash_cny: "100000",
          program: { source: "def decide(data, account, state):\n    return None\n" } },
      ],
    };
    expect(validateBatch(independent).valid).toBe(true);
    expect(validateBatch({ ...independent, alpha: batch.alpha }).valid).toBe(false);
    expect(validateBatch({ ...independent, neutralization: "none" }).valid).toBe(false);
    expect(validateBatch({ ...independent, combinations: "all" }).valid).toBe(false);
    const rejected = await submit.execute?.({
      request_id: "rejected", folder_id: "folder_default", research_kind: "factor_evaluation",
      start_date: "2024-01-02", end_date: "2024-01-31", universe: "top300",
      formula: "unknown_alpha", neutralization: "none",
    }, options("rejected"));
    expect(rejected).toMatchObject({ outcome: "rejected", issues: [{ field: "formula" }] });
    expect(run.toolFailure("rejected")).toEqual({ code: "TOOL_REJECTION", fatal: false });
    const query = { track_id: "track_test", section: "origin" };
    const first = await result.execute?.(query, options("first")) as Record<string, unknown>;
    expect(first).toMatchObject({ section: "result_page", offset: 0, result_section: "origin" });
    expect(Buffer.byteLength(JSON.stringify(first))).toBeLessThan(AGENT_LIMITS.toolResultBytes);
    const next = await result.execute?.({
      section: "result_page", query, result_cursor: first.next_result_cursor,
    }, options("next")) as Record<string, unknown>;
    expect(next.checksum_sha256).toBe(first.checksum_sha256);
    expect(next.offset).toBe((first.json_fragment as string).length);
    expect(run.hasFatalToolFailure()).toBe(false);
  } finally {
    await run.close();
  }
}, 45_000);
