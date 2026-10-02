import { projectResearchA2UIContent, RESEARCH_A2UI_ACTIVITY_TYPE } from "@thesistrace/contracts/research-a2ui";
import type { TimelineEntry, TimelineTurn } from "./chatProtocol";

/** Presentation only: preserve the snapshots and never rewrite Research truth. */
export function progressHistory(turn: TimelineTurn): ReadonlyMap<string, string> {
  const history = new Map<string, string>();
  const laterViews = new Set<string>();
  for (const entry of [...turn.entries].reverse()) {
    const view = resourceView(entry);
    if (view === null) continue;
    if (laterViews.has(view)) {
      history.set(entry.entry_id, "Earlier research view");
    }
    laterViews.add(view);
  }
  return history;
}

function resourceView(entry: TimelineEntry): string | null {
  if (entry.kind !== "a2ui" || entry.payload.activityType !== RESEARCH_A2UI_ACTIVITY_TYPE) return null;
  const projection = projectResearchA2UIContent(entry.payload.content);
  if (!projection.valid || projection.kind !== "ready") return null;
  // The shared contract has already validated the operation and component shapes.
  const operations = projection.content.a2ui_operations as readonly {
    updateComponents?: { components: readonly Record<string, unknown>[] };
  }[];
  const components = operations.flatMap(operation => operation.updateComponents?.components ?? []);
  // Only identical resource-only views can supersede each other. Mixed surfaces
  // contain authored explanations that must remain visible, even after a reload.
  if (components.length !== 1) return null;
  const component = components[0]!;
  if (component.component === "ResearchRun") return JSON.stringify(["run", [component.runId]]);
  if (component.component === "ResearchComparison") return JSON.stringify(["run", component.runIds]);
  if (component.component === "DailyTrack") return JSON.stringify(["track", [component.trackId]]);
  return null;
}
