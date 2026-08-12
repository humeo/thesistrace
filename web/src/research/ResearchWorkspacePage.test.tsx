import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { createDiagnosticsScheduler, type DiagnosticState } from "./diagnostics";
import {
  emptyResearchDraft,
  hasUnexecutedChanges,
  loadResearchDraft,
  persistResearchDraft,
  researchDraftKey,
} from "./draft";
import { ResearchDraftWorkspace } from "./ResearchWorkspacePage";
import { ResearchFolderNavigation } from "./ResearchWorkspacePage";

class MemoryStorage implements Storage {
  private readonly values = new Map<string, string>();
  get length() { return this.values.size; }
  clear() { this.values.clear(); }
  getItem(key: string) { return this.values.get(key) ?? null; }
  key(index: number) { return [...this.values.keys()][index] ?? null; }
  removeItem(key: string) { this.values.delete(key); }
  setItem(key: string, value: string) { this.values.set(key, value); }
}

const folder = { id: "folder_default", name: "Default", is_default: true, created_at: "2026-08-13T00:00:00Z" };
const catalog = {
  fields: [{ identifier: "close_adj", field_id: "price.close_adj", value_type: "numeric_series" as const, description: "Adjusted close", unit: "CNY" }],
  builtins: [{
    identifier: "ts_mean",
    parameters: [{ name: "value", value_type: "numeric_series", minimum: null, maximum: null }],
    result_type: "same_as_first",
    description: "Rolling mean",
    examples: ["ts_mean(close_adj, 20)"],
    missing_value_behavior: "Missing remains missing",
    numeric_behavior: "Finite numeric result",
  }],
};
const data = { readiness: true, dataset_coverage: { start: "2025-01-01", end: "2026-08-12" }, data_through_session: "2026-08-12", last_refresh_at: "2026-08-13T00:00:00Z" };

describe("browser Research Draft", () => {
  it("opens empty when its one Folder key is absent and round-trips the bounded payload", () => {
    const storage = new MemoryStorage();
    const empty = loadResearchDraft(storage, folder.id);
    expect(empty).toEqual(emptyResearchDraft());
    expect(storage.length).toBe(0);

    const draft = { ...empty, name: "Mean reversion", formula: "ts_mean(close_adj, 20)", editor: { anchor: 8, head: 8 } };
    persistResearchDraft(storage, folder.id, draft);
    expect(storage.length).toBe(1);
    expect(storage.key(0)).toBe(researchDraftKey(folder.id));
    expect(loadResearchDraft(storage, folder.id)).toEqual(draft);
  });

  it("keeps independent Draft values under distinct Folder keys", () => {
    const storage = new MemoryStorage();
    persistResearchDraft(storage, "folder_default", { ...emptyResearchDraft(), formula: "close_adj" });
    persistResearchDraft(storage, "folder_signals", { ...emptyResearchDraft(), formula: "volume_shares" });

    expect(loadResearchDraft(storage, "folder_default").formula).toBe("close_adj");
    expect(loadResearchDraft(storage, "folder_signals").formula).toBe("volume_shares");
    storage.removeItem(researchDraftKey("folder_signals"));
    expect(loadResearchDraft(storage, "folder_default").formula).toBe("close_adj");
    expect(loadResearchDraft(storage, "folder_signals")).toEqual(emptyResearchDraft());
  });

  it("requires confirmation only when New would discard unexecuted inputs", () => {
    expect(hasUnexecutedChanges(emptyResearchDraft())).toBe(false);
    expect(hasUnexecutedChanges({ ...emptyResearchDraft(), formula: "close_adj" })).toBe(true);
    const admitted = { ...emptyResearchDraft(), formula: "close_adj" };
    expect(hasUnexecutedChanges({ ...admitted, lastAdmittedBaseline: {
      name: "", formula: "close_adj", hypothesis: "", startDate: "", endDate: "", universe: "", neutralization: "", holdingsCount: "", rebalanceEverySessions: "",
    } })).toBe(false);
  });

  it("renders the DSL as the only Alpha surface without server-edit controls", () => {
    const markup = renderToStaticMarkup(<ResearchDraftWorkspace catalog={catalog} data={data} folder={folder} storage={new MemoryStorage()} />);
    expect(markup).toContain("Alpha formula editor");
    expect(markup).toContain("New Research");
    expect(markup).toContain("Default Folder");
    for (const removed of ["Save", "Refresh", "Revision", "Add Alpha"]) expect(markup).not.toContain(removed);
  });

  it("renders one-level Folder navigation and protects Default management actions", () => {
    const custom = { ...folder, id: "folder_signals", name: "Signals", is_default: false };
    const markup = renderToStaticMarkup(
      <ResearchFolderNavigation
        activeFolder={folder}
        error={null}
        folders={[folder, custom]}
        onCreate={async () => undefined}
        onDelete={async () => undefined}
        onRename={async () => undefined}
      />,
    );
    expect(markup).toContain('href="/research"');
    expect(markup).toContain('href="/research?folder=folder_signals"');
    expect(markup).toContain("Signals");
    expect(markup).not.toContain("Rename Folder");
    expect(markup).not.toContain("Delete Folder");
  });
});

describe("formula diagnostics scheduling", () => {
  it("ignores an older response after a newer Formula request", async () => {
    vi.useFakeTimers();
    const resolvers: Array<(response: Response) => void> = [];
    const request = vi.fn(() => new Promise<Response>((resolve) => resolvers.push(resolve)));
    const states: DiagnosticState[] = [];
    const scheduler = createDiagnosticsScheduler(request as typeof fetch, 10);

    scheduler.diagnose("close_adj", (state) => states.push(state));
    await vi.advanceTimersByTimeAsync(10);
    scheduler.diagnose("ts_mean(close_adj, 20)", (state) => states.push(state));
    await vi.advanceTimersByTimeAsync(10);
    resolvers[1](new Response(JSON.stringify({ valid: true, diagnostics: [] }), { status: 200 }));
    await flushPromises();
    resolvers[0](new Response(JSON.stringify({ valid: false, diagnostics: [] }), { status: 200 }));
    await flushPromises();

    expect(states.at(-1)).toEqual({ kind: "complete", result: { valid: true, diagnostics: [] } });
    scheduler.dispose();
    vi.useRealTimers();
  });

  it("never represents a network failure as valid", async () => {
    vi.useFakeTimers();
    const states: DiagnosticState[] = [];
    const scheduler = createDiagnosticsScheduler(vi.fn(async () => { throw new Error("offline"); }) as typeof fetch, 10);
    scheduler.diagnose("close_adj", (state) => states.push(state));
    await vi.advanceTimersByTimeAsync(10);
    await Promise.resolve();
    expect(states.at(-1)).toEqual({ kind: "unavailable", result: null });
    scheduler.dispose();
    vi.useRealTimers();
  });
});

async function flushPromises(): Promise<void> {
  for (let index = 0; index < 5; index += 1) await Promise.resolve();
}
