import type { Connection } from "./api";
import { useTranslation } from "../i18n";
import { formatNumber } from "../i18n/format";
import type { mcpEn } from "../i18n/messages/mcp";
import { toolPresentation } from "./toolPresentation";
import { Disclosure } from "../components/layout/Disclosure";
import { Badge } from "../components/ui/badge";
import { Empty, EmptyHeader, EmptyTitle, EmptyDescription } from "../components/ui/empty";
import { mcpLayout } from "./mcpLayout";
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
  return <section className={`${mcpLayout.stack} rounded-xl border border-border bg-card p-5`} aria-labelledby="mcp-tools-heading">
    <div className={mcpLayout.row}><h2 id="mcp-tools-heading">{t("toolSet")}</h2><Badge variant="secondary">{checking ? t("checking") : tools ? toolCount(tools.length) : t("unverified")}</Badge></div>
    {!tools ? <Empty><EmptyHeader><EmptyTitle>{checking ? t("discovering") : t("toolNotVerified")}</EmptyTitle><EmptyDescription>{checking ? t("waitingService") : t("checkAgain")}</EmptyDescription></EmptyHeader></Empty> : <div className="grid min-w-0 gap-3 lg:grid-cols-2">{groups.map(groupId => {
      const members = tools.filter(tool => group(tool.name) === groupId);
      return members.length ? <Disclosure key={groupId} title={<span className={mcpLayout.row}><span>{t(`groups.${groupId}`)}</span><Badge variant="secondary">{toolCount(members.length)}</Badge></span>}>
        {members.map(tool => <Disclosure key={tool.name} title={toolPresentation[tool.name] ? <><span className={mcpLayout.toolLabel}><strong>{t(`toolNames.${tool.name}.title` as `toolNames.${KnownToolName}.title`)}</strong><span>{t(`toolNames.${tool.name}.description` as `toolNames.${KnownToolName}.description`)}</span></span><Badge variant="secondary">{t(`effects.${toolPresentation[tool.name].effect}`)}</Badge></> : title(tool.name)}><div><code>{tool.name}</code>{toolPresentation[tool.name] ? <p>{t("permission")} <code>{toolPresentation[tool.name].scope}</code></p> : null}<p>{toolPresentation[tool.name] ? t(`toolDetails.${tool.name}` as `toolDetails.${KnownToolName}`) : t("unrecognizedTool")}</p></div></Disclosure>)}
      </Disclosure> : null;
    })}</div>}
  </section>;
}
