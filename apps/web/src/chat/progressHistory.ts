import { projectResearchA2UIContent, RESEARCH_A2UI_ACTIVITY_TYPE } from "@thesistrace/contracts/research-a2ui";
import type { TimelineEntry, TimelineTurn } from "./chatProtocol";

/** Presentation only: preserve the snapshots and never rewrite Research truth. */
export function progressHistory(turn: TimelineTurn): ReadonlyMap<string, string> {
  const history = new Map<string, string>();
  const laterRuns = new Set<string>();
  for (const entry of [...turn.entries].reverse()) {
    const runs = surfaceRuns(entry);
    if (runs.length === 0) continue;
    const superseded = runs.every((run) => laterRuns.has(run.runId));
    if (superseded) {
      history.set(entry.entry_id, "Earlier research view");
    }
    for (const run of runs) laterRuns.add(run.runId);
  }
  return history;
}

function surfaceRuns(entry: TimelineEntry): readonly { runId: string }[] {
  if (entry.kind !== "a2ui" || entry.payload.activityType !== RESEARCH_A2UI_ACTIVITY_TYPE) return [];
  const projection = projectResearchA2UIContent(entry.payload.content);
  if (!projection.valid || projection.kind !== "ready") return [];
  // The shared contract has already validated the operation and component shapes.
  const operations = projection.content.a2ui_operations as readonly {
    updateComponents?: { components: readonly Record<string, unknown>[] };
  }[];
  return operations.flatMap((operation) => (operation.updateComponents?.components ?? [])
    .flatMap((component) => component.component === "ResearchRun" ? [{ runId: component.runId as string }]
      : component.component === "ResearchComparison" ? (component.runIds as string[]).map(runId => ({ runId }))
      : component.component === "DailyTrack" ? [{ runId: component.trackId as string }] : []));
}
