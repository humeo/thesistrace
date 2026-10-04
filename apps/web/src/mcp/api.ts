import { z } from "zod";
import { coreFetch } from "../auth/coreFetch";
const app = z.object({ id: z.string().uuid(), client_id: z.string(), name: z.string().nullable(), scopes: z.array(z.string()), authorized_at: z.string().datetime() });
export type AuthorizedApp = z.infer<typeof app>;
const connections = z.object({ server_url: z.string().url(), apps: z.array(app) });
const connection = z.object({ checked_at: z.string().datetime(), tools: z.array(z.object({ name: z.string(), description: z.string() })) });
export type Connection = z.infer<typeof connection>;
export async function loadConnections(signal?: AbortSignal) {
  const response = await coreFetch("/api/auth/mcp/connections", { signal });
  if (!response.ok) throw new Error("Could not load your connections.");
  return connections.parse(await response.json());
}
export async function checkConnection(signal?: AbortSignal): Promise<Connection> {
  const response = await coreFetch("/api/agent/mcp/connection", { signal });
  if (!response.ok) throw new Error("Connection could not be verified.");
  return connection.parse(await response.json());
}
export async function revokeApp(id: string) {
  const response = await coreFetch("/api/auth/mcp/revoke", { method: "POST", body: JSON.stringify({ id }) });
  if (!response.ok) throw new Error("Access could not be revoked. Please try again.");
}

export const authoringTopics = ["workflow", "formula", "python_sdk", "examples"] as const;
export type AuthoringTopic = typeof authoringTopics[number];
const authoringReference = z.object({
  topic: z.enum(authoringTopics), title: z.string(), overview: z.array(z.string()), found: z.boolean(),
  symbols: z.array(z.object({ symbol: z.string(), description: z.string() })),
  entry: z.object({
    symbol: z.string(), description: z.string(), signature: z.string().nullable(),
    parameters: z.record(z.string()), returns: z.string().nullable(), notes: z.array(z.string()),
    constraints: z.record(z.unknown()), data_schema: z.record(z.unknown()).nullable(),
    examples: z.array(z.object({
      title: z.string(), language: z.enum(["python", "formula", "json"]), source: z.string(),
      entrypoint: z.string().nullable(), context: z.enum(["signal", "exposure"]).nullable(),
    })),
  }).nullable(),
});
export type AuthoringReference = z.infer<typeof authoringReference>;
export async function loadAuthoringReference(topic: AuthoringTopic, symbol: string | null, signal?: AbortSignal) {
  const query = new URLSearchParams({ topic });
  if (symbol !== null) query.set("symbol", symbol);
  const response = await coreFetch(`/api/research/authoring-reference?${query}`, { signal });
  if (!response.ok) throw new Error("Authoring reference unavailable");
  return authoringReference.parse(await response.json());
}
