import { describe, expect, it, vi } from "vitest";
import { checkMcpConnection } from "./mcp-connection.js";
import type { DiscoveredMcpTools } from "./mcp-run.js";

describe("MCP service check", () => {
  it("returns discovered tools and releases transport without executing tools", async () => {
    let closed = false;
    const execute = vi.fn(async () => { throw Error("must not execute research"); });
    const tools = { get_research_context: { id: "get_research_context", description: "Research context", execute } } as DiscoveredMcpTools;
    const result = await checkMcpConnection(async () => ({ tools, close: async () => { closed = true; }, hasFatalToolFailure: () => false, toolFailure: () => undefined }), new Headers());
    expect(result.tools).toEqual([{ name: "get_research_context", description: "Research context" }]);
    expect(closed).toBe(true);
    expect(execute).not.toHaveBeenCalled();
  });
  it("reports failed discovery instead of inventing an available service", async () => {
    await expect(checkMcpConnection(async () => { throw Error("discovery failed"); }, new Headers())).rejects.toThrow("discovery failed");
  });
});
