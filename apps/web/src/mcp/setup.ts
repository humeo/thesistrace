export const clients = { codex: "Codex", claude: "Claude Code", other: "Other client" } as const;
export type McpClient = keyof typeof clients;
export function setupPrompt(client: McpClient, endpoint: string): string {
  return `Add ThesisTrace MCP to ${client === "other" ? "this AI client" : clients[client]} using ${endpoint}. If authorization is needed, guide me through signing in to ThesisTrace and approving access. Then retrieve the tool list and report the connection status and available tools. Preserve all other MCP configurations and do not run any research tasks.`;
}
export function addCommand(client: Exclude<McpClient, "other">, endpoint: string): string {
  const quoted = `'${endpoint.replaceAll("'", "'\\''")}'`;
  return client === "codex" ? `codex mcp add thesistrace --url ${quoted}`
    : `claude mcp add --transport http --scope user thesistrace ${quoted}`;
}
export const scopeLabels: Record<string, string> = {
  "research:read": "Read research context, runs and results",
  "research:execute": "Create research runs and batches",
  "tracking:read": "Read daily tracks and observations",
  "tracking:execute": "Start, refresh and retry daily tracks",
  offline_access: "Keep access using a refresh token",
};
