// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, test, vi } from "vitest";
vi.mock("./AlphaFormulaEditor", () => ({ AlphaFormulaEditor: () => null }));
import { ResearchWorkspacePage } from "./ResearchWorkspacePage";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
test.each(["success", "failure"])("a late Folder A %s cannot replace the loaded Folder B", async (outcome) => {
  const folders = [{ id: "folder_default", name: "Default", is_default: true, created_at: "2026-09-07T00:00:00Z" },
    { id: "folder_b", name: "B", is_default: false, created_at: "2026-09-07T00:00:00Z" }];
  let settle!: (response: Response) => void;
  const slow = new Promise<Response>((resolve) => { settle = resolve; });
  let folderReads = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: string) => {
    if (input === "/api/research-folders") {
      if (++folderReads === 1) return slow; // Deliberately ignores cancellation.
      return Response.json({ items: folders, next_cursor: null });
    }
    if (input === "/api/alpha/catalog") return Response.json({ fields: [], builtins: [] });
    if (input === "/api/data") return Response.json({ market_research_readiness: false });
    throw new Error("Unexpected test request");
  }));
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  try {
    await act(async () => root.render(<ResearchWorkspacePage researcherId="owner" location={{ pathname: "/research", search: "", hash: "" }} />));
    await act(async () => root.render(<ResearchWorkspacePage researcherId="owner" location={{ pathname: "/research", search: "?folder=folder_b", hash: "" }} />));
    expect(container.querySelector('[aria-current="page"]')?.textContent).toBe("B");
    await act(async () => { settle(outcome === "success" ? Response.json({ items: folders, next_cursor: null }) : new Response(null, { status: 500 })); });
    expect(container.querySelector('[aria-current="page"]')?.textContent).toBe("B");
    expect(container.querySelector('[role="alert"]')).toBeNull();
  } finally {
    settle(new Response(null, { status: 500 }));
    await act(async () => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
  }
});
