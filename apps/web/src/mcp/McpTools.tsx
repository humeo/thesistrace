import { useState } from "react";
import type { Connection } from "./api";
import { useTranslation } from "../i18n";
import { formatNumber } from "../i18n/format";
import type { mcpEn } from "../i18n/messages/mcp";
import { toolPresentation } from "./toolPresentation";
import { Disclosure } from "../components/layout/Disclosure";
import { Badge } from "../components/ui/badge";
import { Empty, EmptyHeader, EmptyTitle, EmptyDescription } from "../components/ui/empty";
import { ToggleGroup, ToggleGroupItem } from "../components/ui/toggle-group";
import { Separator } from "../components/ui/separator";
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
  const [selectedGroup, setSelectedGroup] = useState<Group>("preparation");
  const toolCount = (count: number) => t("toolCount", { count, countLabel: formatNumber(count) });
  const discoveredGroups = groups.map(id => ({ id, members: tools?.filter(tool => group(tool.name) === id) ?? [] })).filter(entry => entry.members.length > 0);
  const activeGroup = discoveredGroups.find(entry => entry.id === selectedGroup) ?? discoveredGroups[0];
  return <section className="flex min-w-0 flex-col gap-6" aria-labelledby="mcp-tools-heading">
    <div className={mcpLayout.row}><h2 id="mcp-tools-heading" className={mcpLayout.sectionTitle}>{t("toolSet")}</h2><span className="text-sm text-muted-foreground">{checking ? t("checking") : tools ? toolCount(tools.length) : t("unverified")}</span></div>
    {!tools ? <Empty><EmptyHeader><EmptyTitle>{checking ? t("discovering") : t("toolNotVerified")}</EmptyTitle><EmptyDescription>{checking ? t("waitingService") : t("checkAgain")}</EmptyDescription></EmptyHeader></Empty> : !activeGroup ? <Empty><EmptyHeader><EmptyTitle>{t("noTools")}</EmptyTitle></EmptyHeader></Empty> : <>
      <Separator />
      <div className="grid min-w-0 grid-cols-[200px_1px_minmax(0,1fr)] gap-6">
        <ToggleGroup orientation="vertical" size="lg" spacing={1} value={[activeGroup.id]} onValueChange={values => { if (values[0]) setSelectedGroup(values[0] as Group); }} aria-label={t("toolCategories")} className="w-full self-start">
          {discoveredGroups.map(entry => <ToggleGroupItem key={entry.id} value={entry.id} aria-label={`${t(`groups.${entry.id}`)} ${toolCount(entry.members.length)}`} className="justify-between gap-3"><span>{t(`groups.${entry.id}`)}</span><span className="text-sm font-normal text-muted-foreground">{formatNumber(entry.members.length)}</span></ToggleGroupItem>)}
        </ToggleGroup>
        <Separator orientation="vertical" />
        <div className="min-w-0" role="region" aria-label={t(`groups.${activeGroup.id}`)}>
          {activeGroup.members.map(tool => <Disclosure variant="row" key={tool.name} title={toolPresentation[tool.name] ? <><span className={`${mcpLayout.toolLabel} py-3`}><span className="font-medium">{t(`toolNames.${tool.name}.title` as `toolNames.${KnownToolName}.title`)}</span><span className="font-normal text-muted-foreground">{t(`toolNames.${tool.name}.description` as `toolNames.${KnownToolName}.description`)}</span></span><Badge variant="secondary">{t(`effects.${toolPresentation[tool.name].effect}`)}</Badge></> : <span className="py-3">{title(tool.name)}</span>}><div className={`${mcpLayout.stack} [&_code]:[overflow-wrap:anywhere] [&_code]:text-sm`}><code>{tool.name}</code>{toolPresentation[tool.name] ? <p>{t("permission")} <code>{toolPresentation[tool.name].scope}</code></p> : null}<p>{toolPresentation[tool.name] ? t(`toolDetails.${tool.name}` as `toolDetails.${KnownToolName}`) : t("unrecognizedTool")}</p></div></Disclosure>)}
        </div>
      </div>
      <Separator />
    </>}
  </section>;
}
