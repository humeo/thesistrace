import { i18n } from "../i18n";

export const clients = { codex: "Codex", claude: "Claude Code", other: "Other client" } as const;
export const mcpServerName = "quantgrove";
export type McpClient = keyof typeof clients;
export function setupPrompt(client: McpClient, endpoint: string): string {
  return i18n.t("mcp:setupPrompt", { client: client === "other" ? i18n.t("mcp:thisClient") : clients[client], endpoint });
}
export function addCommand(client: Exclude<McpClient, "other">, endpoint: string): string {
  const quoted = `'${endpoint.replaceAll("'", "'\\''")}'`;
  return client === "codex" ? `codex mcp add ${mcpServerName} --url ${quoted}`
    : `claude mcp add --transport http --scope user ${mcpServerName} ${quoted}`;
}
export function scopeLabel(scope: string): string {
  switch (scope) {
    case "research:read": return i18n.t("mcp:scopes.researchRead");
    case "research:execute": return i18n.t("mcp:scopes.researchExecute");
    case "tracking:read": return i18n.t("mcp:scopes.trackingRead");
    case "tracking:execute": return i18n.t("mcp:scopes.trackingExecute");
    case "offline_access": return i18n.t("mcp:scopes.offlineAccess");
    default: return scope;
  }
}
