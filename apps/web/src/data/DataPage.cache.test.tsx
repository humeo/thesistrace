// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { notifyManager } from "@tanstack/react-query";
import { DataPage } from "./DataPage";
import { WorkspaceQueryProvider } from "../shell/WorkspaceQueryProvider";
import { setCoreUnauthorizedHandler } from "../auth/coreFetch";
import { i18n } from "../i18n";
import { workbenchData } from "../../browser/fixtures/workbench-data";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
beforeEach(() => notifyManager.setNotifyFunction(callback => { act(callback); }));
afterEach(() => {
  notifyManager.setNotifyFunction(callback => callback());
  vi.unstubAllGlobals();
});

function deferredResponse() {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>(settle => { resolve = settle; });
  return { promise, resolve };
}

async function eventually(assertion: () => void) {
  await vi.waitFor(async () => {
    await act(async () => {});
    assertion();
  });
}

async function mount() {
  await i18n.changeLanguage("en");
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  const render = (researcherId: string) => act(async () => root.render(
    <WorkspaceQueryProvider researcherId={researcherId}><DataPage /></WorkspaceQueryProvider>,
  ));
  const dispose = async () => { await act(async () => root.unmount()); container.remove(); };
  return { container, render, dispose };
}

test("refresh failure retains loaded Data and a later reload replaces it", async () => {
  const pending = deferredResponse();
  let response = () => Promise.resolve(Response.json(workbenchData));
  vi.stubGlobal("fetch", vi.fn(() => response()));
  const { container, render, dispose } = await mount();
  const reload = () => Array.from(container.querySelectorAll("button")).find(button => button.textContent === "Reload status")!;
  try {
    await render("owner");
    await eventually(() => expect(container.querySelector(".data-field-table")).not.toBeNull());
    const table = container.querySelector(".data-field-table");
    response = () => pending.promise;
    await act(async () => reload().click());
    expect(container.querySelector(".data-field-table")).toBe(table);
    await eventually(() => expect(reload().disabled).toBe(true));
    await act(async () => pending.resolve(new Response(null, { status: 503 })));
    await eventually(() => expect(container.querySelector('[role="alert"]')).not.toBeNull());
    expect(container.querySelector(".data-field-table")).toBe(table);
    expect(container.textContent).toContain("2010-01-04 — 2026-08-13");

    response = () => Promise.resolve(Response.json({ ...workbenchData, market_coverage: { start: "2010-01-04", end: "2026-10-05" } }));
    await act(async () => reload().click());
    await eventually(() => expect(container.textContent).toContain("2010-01-04 — 2026-10-05"));
    expect(container.querySelector('[role="alert"]')).toBeNull();
  } finally {
    pending.resolve(new Response(null, { status: 503 }));
    await dispose();
  }
});

test.each([200, 401])("changing Researcher discards cached facts and ignores the old pending %s response", async (status) => {
  const oldRefresh = deferredResponse();
  const nextOwner = deferredResponse();
  let response = () => Promise.resolve(Response.json(workbenchData));
  let oldSignal: AbortSignal | undefined;
  vi.stubGlobal("fetch", vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
    const pending = response();
    if (pending === oldRefresh.promise) oldSignal = init?.signal ?? undefined;
    return pending;
  }));
  let session = "authenticated";
  const resetUnauthorized = setCoreUnauthorizedHandler(() => { session = "anonymous"; });
  const { container, render, dispose } = await mount();
  try {
    await render("owner-a");
    await eventually(() => expect(container.textContent).toContain("2010-01-04 — 2026-08-13"));
    response = () => oldRefresh.promise;
    const reload = Array.from(container.querySelectorAll("button")).find(button => button.textContent === "Reload status")!;
    await act(async () => reload.click());
    response = () => nextOwner.promise;
    await render("owner-b");
    expect(oldSignal?.aborted).toBe(true);
    expect(container.textContent).not.toContain("2026-08-13");
    expect(container.querySelector(".data-field-table")).toBeNull();
    await act(async () => oldRefresh.resolve(status === 200 ? Response.json(workbenchData) : new Response(null, { status })));
    expect(container.textContent).not.toContain("2026-08-13");
    expect(session).toBe("authenticated");
    await act(async () => nextOwner.resolve(Response.json({ ...workbenchData, market_coverage: { start: "2010-01-04", end: "2026-10-05" } })));
    await eventually(() => expect(container.textContent).toContain("2010-01-04 — 2026-10-05"));
  } finally {
    oldRefresh.resolve(new Response(null, { status: 503 }));
    nextOwner.resolve(new Response(null, { status: 503 }));
    await dispose();
    resetUnauthorized();
  }
});
