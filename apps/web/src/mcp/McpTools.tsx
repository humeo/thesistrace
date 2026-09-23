import type { Connection } from "./api";
import { useTranslation } from "../i18n";
import { formatNumber } from "../i18n/format";
import type { mcpEn } from "../i18n/messages/mcp";
import { toolPresentation } from "./toolPresentation";
type KnownToolName = keyof typeof mcpEn.toolNames;
const groups = ["preparation", "runs", "batches", "tracks", "other"] as const;
type Group = typeof groups[number];
function group(name: string): Group {
  if (name.includes("daily_track")) return "tracks";
  if (name.includes("research_batch")) return "batches";
  if (name.includes("research_run")) return "runs";
  return toolPresentation[name] ? "preparation" : "other";
}
function title(name: string): string { return name.replaceAll("_", " ").replace(/^./, char => char.toUpperCase()); }
export function McpTools({ tools, checking }: { tools: Connection["tools"] | null; checking: boolean }) {
  const { t } = useTranslation("mcp");
  const toolCount = (count: number) => t("toolCount", { count, countLabel: formatNumber(count) });
  return <section aria-labelledby="mcp-tools-heading">
    <div className="mcp-section-heading"><h2 id="mcp-tools-heading">{t("toolSet")}</h2><span className="mcp-tag">{checking ? t("checking") : tools ? toolCount(tools.length) : t("unverified")}</span></div>
    {!tools ? <div className="mcp-empty"><div><strong>{checking ? t("discovering") : t("toolNotVerified")}</strong><p>{checking ? t("waitingService") : t("checkAgain")}</p></div></div> : groups.map(groupId => {
      const members = tools.filter(tool => group(tool.name) === groupId);
      return members.length ? <details className="mcp-tool-group" key={groupId}>
        <summary><span>{t(`groups.${groupId}`)}</span><small>{toolCount(members.length)}</small></summary>
        {members.map(tool => <details className="mcp-tool" key={tool.name}><summary>{toolPresentation[tool.name] ? <><span className="mcp-tool-label"><strong>{t(`toolNames.${tool.name}.title` as `toolNames.${KnownToolName}.title`)}</strong><span>{t(`toolNames.${tool.name}.description` as `toolNames.${KnownToolName}.description`)}</span></span><span className="mcp-tag">{t(`effects.${toolPresentation[tool.name].effect}`)}</span></> : title(tool.name)}</summary><div><code>{tool.name}</code>{toolPresentation[tool.name] ? <p>{t("permission")} <code>{toolPresentation[tool.name].scope}</code></p> : null}<p>{tool.description}</p></div></details>)}
      </details> : null;
    })}
  </section>;
}
