// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { notifyManager } from "@tanstack/react-query";
import { expect, test, vi } from "vitest";
import { WorkspaceQueryProvider } from "../shell/WorkspaceQueryProvider";
import { ResearchRunsPage, type ResearchRun } from "./ResearchRunsPage";

const run: ResearchRun = {
  id: "run_cafebabefeed1234", name: "Loaded factor", research_kind: "factor_evaluation", status: "succeeded",
  folder_id: "folder_default", created_at: "2026-10-05T00:00:00Z", start_date: "2026-08-01", end_date: "2026-08-31", formula_summary: "rank(close)",
};

test("returning to Research Runs shows cached rows while a fresh response is pending, then replaces them", async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  notifyManager.setNotifyFunction(callback => { act(callback); });
  let resolve!: (response: Response) => void;
  const pending = new Promise<Response>(settle => { resolve = settle; });
  let refreshing = false;
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path === "/api/research-folders") return Response.json({ items: [
      { id: "folder_default", name: "Default", is_default: true, created_at: "2026-08-01T00:00:00Z" },
    ], next_cursor: null });
    if (path.startsWith("/api/research-runs?")) return refreshing ? pending : Response.json({ items: [run], total_count: 1 });
    throw new Error(`Unexpected request: ${path}`);
  });
  const host = document.createElement("div"); document.body.append(host);
  const root = createRoot(host);
  const render = (show: boolean, researcherId = "owner") => act(async () => root.render(
    <WorkspaceQueryProvider researcherId={researcherId}>{show ? <ResearchRunsPage researcherId={researcherId} /> : <p>Another workspace page</p>}</WorkspaceQueryProvider>,
  ));
  try {
    await render(true);
    await vi.waitFor(() => expect(host.textContent).toContain("Loaded factor"));
    await render(false);
    refreshing = true;
    await render(true);
    expect(host.textContent).toContain("Loaded factor");
    await act(async () => resolve(Response.json({ items: [{ ...run, name: "Renamed elsewhere" }], total_count: 1 })));
    await vi.waitFor(() => expect(host.textContent).toContain("Renamed elsewhere"));
    expect(host.textContent).not.toContain("Loaded factor");
  } finally {
    resolve(Response.json({ items: [], total_count: 0 }));
    await act(async () => root.unmount()); host.remove();
    notifyManager.setNotifyFunction(callback => callback()); vi.unstubAllGlobals();
  }
});
