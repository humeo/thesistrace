// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, test, vi } from "vitest";
vi.mock("./AlphaFormulaEditor", () => ({ AlphaFormulaEditor: () => null }));
import { ResearchWorkspacePage } from "./ResearchWorkspacePage";
import { i18n } from "../i18n";

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
    if (input === "/api/data") return Response.json({ market_research_readiness: false, catalog: { fields: [], industries: [], builtins: [], generation_manifest_sha256: null } });
    throw new Error("Unexpected test request");
  }));
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  try {
    await act(async () => { await i18n.changeLanguage("en"); });
    await act(async () => root.render(<ResearchWorkspacePage researcherId="owner" location={{ pathname: "/research", search: "", hash: "" }} />));
    await act(async () => root.render(<ResearchWorkspacePage researcherId="owner" location={{ pathname: "/research", search: "?folder=folder_b", hash: "" }} />));
    expect(container.querySelector('[aria-current="page"]')?.textContent).toBe("B");
    const name = container.querySelector<HTMLInputElement>("#research-name")!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(name, "My 中文 idea");
      name.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const menu = container.querySelector<HTMLDetailsElement>(".research-folder-navigation")!;
    menu.open = true;
    const newFolderName = container.querySelector<HTMLInputElement>("#new-folder-name")!;
    newFolderName.focus();
    const beforeSwitch = vi.mocked(fetch).mock.calls.length;
    await act(async () => { await i18n.changeLanguage("zh-CN"); });
    expect(container.querySelector('[aria-label="研究名称"]')).toBe(name);
    expect(name.value).toBe("My 中文 idea");
    expect(menu.open).toBe(true);
    expect(document.activeElement).toBe(newFolderName);
    expect(vi.mocked(fetch).mock.calls.length).toBe(beforeSwitch);
    await act(async () => { settle(outcome === "success" ? Response.json({ items: folders, next_cursor: null }) : new Response(null, { status: 500 })); });
    expect(container.querySelector('[aria-current="page"]')?.textContent).toBe("B");
    expect(container.querySelector('[role="alert"]')).toBeNull();
  } finally {
    settle(new Response(null, { status: 500 }));
    await act(async () => root.unmount());
    await i18n.changeLanguage("en");
    container.remove();
    vi.unstubAllGlobals();
  }
});
