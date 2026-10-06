// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { notifyManager } from "@tanstack/react-query";
vi.mock("./AlphaFormulaEditor", () => ({ AlphaFormulaEditor: () => null }));
import { ResearchWorkspacePage } from "./ResearchWorkspacePage";
import { WorkspaceQueryProvider } from "../shell/WorkspaceQueryProvider";
import { workbenchData } from "../../browser/fixtures/workbench-data";
import { i18n } from "../i18n";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
beforeEach(() => notifyManager.setNotifyFunction(callback => { act(callback); }));
afterEach(() => notifyManager.setNotifyFunction(callback => callback()));
test.each(["success", "failure"])("a late previous Researcher %s cannot replace the current Folder or draft", async (outcome) => {
  const folders = [{ id: "folder_default", name: "Default", is_default: true, created_at: "2026-09-07T00:00:00Z" },
    { id: "folder_b", name: "B", is_default: false, created_at: "2026-09-07T00:00:00Z" }];
  let settle!: (response: Response) => void;
  const slow = new Promise<Response>((resolve) => { settle = resolve; });
  let folderReads = 0;
  let oldSignal: AbortSignal | undefined;
  const drafts = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => drafts.get(key) ?? null,
    setItem: (key: string, value: string) => { drafts.set(key, value); },
    removeItem: (key: string) => { drafts.delete(key); },
  });
  vi.stubGlobal("fetch", vi.fn(async (input: string, init?: RequestInit) => {
    if (input === "/api/research-folders") {
      if (++folderReads === 1) {
        oldSignal = init?.signal ?? undefined;
        return slow; // Deliberately ignores cancellation.
      }
      return Response.json({ items: folders, next_cursor: null });
    }
    if (input === "/api/data") return Response.json(workbenchData);
    throw new Error("Unexpected test request");
  }));
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  try {
    await act(async () => { await i18n.changeLanguage("en"); });
    await act(async () => root.render(<WorkspaceQueryProvider researcherId="owner-a"><ResearchWorkspacePage researcherId="owner-a" location={{ pathname: "/research", search: "", hash: "" }} /></WorkspaceQueryProvider>));
    await act(async () => root.render(<WorkspaceQueryProvider researcherId="owner-b"><ResearchWorkspacePage researcherId="owner-b" location={{ pathname: "/research", search: "?folder=folder_b", hash: "" }} /></WorkspaceQueryProvider>));
    expect(oldSignal?.aborted).toBe(true);
    await vi.waitFor(() => expect(container.querySelector('[aria-labelledby="research-choice-factor_evaluation"]')).not.toBeNull());
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[aria-labelledby="research-choice-factor_evaluation"]')!.click();
      await vi.dynamicImportSettled();
    });
    expect(container.querySelector('[aria-label="Research Folders"]')?.textContent).toContain("B folder");
    await act(async () => container.querySelector<HTMLButtonElement>('[title="Edit research name"]')!.click());
    const name = container.querySelector<HTMLInputElement>("#research-name")!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(name, "My 中文 idea");
      name.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const menu = container.querySelector<HTMLButtonElement>('[aria-label="Research Folders"]')!;
    await act(async () => menu.click());
    await act(async () => Array.from(document.querySelectorAll<HTMLElement>('[role="menuitem"]'))
      .find(item => item.textContent?.trim() === "New Folder")!.click());
    const newFolderName = document.querySelector<HTMLInputElement>("#new-folder-name")!;
    newFolderName.focus();
    const beforeSwitch = vi.mocked(fetch).mock.calls.length;
    await act(async () => { await i18n.changeLanguage("zh-CN"); });
    expect(container.querySelector('[title="编辑研究名称"]')?.textContent).toContain("My 中文 idea");
    expect(menu.getAttribute("aria-expanded")).toBe("false");
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain("新建文件夹");
    expect(document.activeElement).toBe(newFolderName);
    expect(vi.mocked(fetch).mock.calls.length).toBe(beforeSwitch);
    await act(async () => { settle(outcome === "success" ? Response.json({ items: folders, next_cursor: null }) : new Response(null, { status: 500 })); });
    expect(container.querySelector('[aria-label="研究文件夹"]')?.textContent).toContain("B文件夹");
    expect(container.querySelector('[role="alert"]')).toBeNull();
  } finally {
    settle(new Response(null, { status: 500 }));
    await act(async () => root.unmount());
    await i18n.changeLanguage("en");
    container.remove();
    vi.unstubAllGlobals();
  }
}, 15_000);

test("a pending shared Folder list opens the latest requested Folder", async () => {
  const folders = [
    { id: "folder_default", name: "Default", is_default: true, created_at: "2026-09-07T00:00:00Z" },
    { id: "folder_b", name: "B", is_default: false, created_at: "2026-09-07T00:00:00Z" },
  ];
  let settle!: (response: Response) => void;
  const slow = new Promise<Response>(resolve => { settle = resolve; });
  vi.stubGlobal("fetch", vi.fn(async (input: string) => {
    if (input === "/api/research-folders") return slow;
    if (input === "/api/data") return Response.json(workbenchData);
    throw new Error("Unexpected test request");
  }));
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  const render = (search: string) => act(async () => root.render(
    <WorkspaceQueryProvider researcherId="pending-owner"><ResearchWorkspacePage researcherId="pending-owner" location={{ pathname: "/research", search, hash: "" }} /></WorkspaceQueryProvider>,
  ));
  try {
    await i18n.changeLanguage("en");
    await render("");
    await render("?folder=folder_b");
    await act(async () => settle(Response.json({ items: folders, next_cursor: null })));
    await vi.waitFor(() => expect(container.querySelector('[aria-label="Research Folders"]')?.textContent).toContain("B folder"));
  } finally {
    settle(new Response(null, { status: 500 }));
    await act(async () => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
  }
});
