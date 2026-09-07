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
