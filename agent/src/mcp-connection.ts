import { randomUUID } from "node:crypto";
import type { McpRunFactory } from "./mcp-run.js";
export type McpConnection = Readonly<{ checked_at: string; tools: ReadonlyArray<{ name: string; description: string }> }>;

// Discovery uses the same authenticated transport as chat, without creating a
// chat session, invoking a model, or executing a research tool.
export async function checkMcpConnection(factory: McpRunFactory, headers: Headers): Promise<McpConnection> {
  const connection = await factory(headers, `connection-check-${randomUUID()}`);
  try {
    return {
      checked_at: new Date().toISOString(),
      tools: Object.entries(connection.tools).map(([name, tool]) => ({ name, description: tool.description ?? "" })),
    };
  } finally { await connection.close(); }
}
