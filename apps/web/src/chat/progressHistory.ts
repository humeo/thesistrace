import { projectResearchA2UIContent, RESEARCH_A2UI_ACTIVITY_TYPE } from "@thesistrace/contracts/research-a2ui";
import type { TimelineEntry, TimelineTurn } from "./chatProtocol";

/** Presentation only: preserve the snapshots and never rewrite Research truth. */
export function progressHistory(turn: TimelineTurn): ReadonlyMap<string, string> {
  const history = new Map<string, string>();
  const laterRuns = new Set<string>();
  const ended = ["completed", "failed", "stopped"].includes(turn.status);
  for (const entry of [...turn.entries].reverse()) {
    const runs = surfaceRuns(entry);
    if (runs.length === 0) continue;
    const pending = runs.some((run) => ["queued", "running", "cancelling"].includes(run.status));
    const superseded = runs.every((run) => laterRuns.has(run.runId));
    if (pending && (superseded || ended)) {
      history.set(entry.entry_id, superseded ? "Earlier progress" : "Last observed progress");
    }
    for (const run of runs) laterRuns.add(run.runId);
  }
  return history;
}

function surfaceRuns(entry: TimelineEntry): readonly { runId: string; status: string }[] {
  if (entry.kind !== "a2ui" || entry.payload.activityType !== RESEARCH_A2UI_ACTIVITY_TYPE) return [];
  const projection = projectResearchA2UIContent(entry.payload.content);
  if (!projection.valid || projection.kind !== "ready") return [];
  // The shared contract has already validated the operation and component shapes.
  const operations = projection.content.a2ui_operations as readonly {
    updateComponents?: { components: readonly Record<string, unknown>[] };
  }[];
  return operations.flatMap((operation) => (operation.updateComponents?.components ?? [])
    .filter((component) => component.component === "ResearchRunStatus")
    .map((component) => ({ runId: component.runId as string, status: component.status as string })));
}

export function isProgressSurface(entry: TimelineEntry): boolean {
  return surfaceRuns(entry).some((run) => ["queued", "running", "cancelling"].includes(run.status));
}
