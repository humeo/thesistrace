// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, test, vi } from "vitest";
import * as client from "./operatorMutationClient";
import { OperatorDataPage } from "./OperatorDataPage";
import { WorkspaceQueryProvider } from "../shell/WorkspaceQueryProvider";
import { DataPage } from "../data/DataPage";
import { workbenchData } from "../../browser/fixtures/workbench-data";
import { notifyManager } from "@tanstack/react-query";

vi.mock("./OperatorDatasetStatus", () => ({ OperatorDatasetStatus: () => null }));
vi.mock("./OperatorFinancialRefreshPanel", () => ({ OperatorFinancialRefreshPanel: () => null }));
vi.mock("./OperatorIndustryRefreshPanel", () => ({ OperatorIndustryRefreshPanel: () => null }));

test("an accepted publication refreshes cached Data even when the status panel is unavailable", async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  notifyManager.setNotifyFunction(callback => { act(callback); });
  let published = false;
  vi.stubGlobal("fetch", () => Promise.resolve(Response.json(published
    ? { ...workbenchData, market_coverage: { start: "2010-01-04", end: "2026-10-05" } }
    : workbenchData)));
  vi.spyOn(client, "confirmDatasetRefreshProof").mockResolvedValue({ expiresAt: "2026-10-06T08:00:00Z", proof: "test-only" });
  vi.spyOn(client, "submitDatasetRefresh").mockImplementation(async request => {
    published = true;
    return { ...request, attemptCount: 1, dataThroughSession: "2026-10-05", failureCode: null, kind: "dataset", phase: null, completedStages: [], lastFailureCode: null,
      lastRefreshAt: "2026-10-05T10:00:00Z", outcome: "published", status: "succeeded" };
  });
  const host = document.createElement("div"); document.body.append(host);
  const root = createRoot(host);
  const render = (data: boolean) => act(async () => root.render(<WorkspaceQueryProvider researcherId="operator-receipt">
    {data ? <DataPage /> : <OperatorDataPage />}
  </WorkspaceQueryProvider>));
  try {
    await render(true);
    await vi.waitFor(() => expect(host.textContent).toContain("2010-01-04 — 2026-08-13"));
    await render(false);
    await act(async () => {
      const input = host.querySelector<HTMLInputElement>("#operator-market-as-of")!;
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "2026-10-05");
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await act(async () => host.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    await act(async () => document.querySelector('[role="dialog"] form')!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    expect(host.textContent).toContain("Dataset published");
    await render(true);
    await vi.waitFor(() => expect(host.textContent).toContain("2010-01-04 — 2026-10-05"));
  } finally {
    await act(async () => root.unmount()); host.remove();
    notifyManager.setNotifyFunction(callback => callback());
    vi.restoreAllMocks(); vi.unstubAllGlobals();
  }
});

test.each(["accepted", "reconciled"])("restores Market focus after the %s receipt enables its trigger", async (path) => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  // A frame is allowed to precede the React commit that enables the trigger.
  vi.spyOn(window, "requestAnimationFrame").mockImplementation(callback => { callback(0); return 1; });
  vi.spyOn(client, "confirmDatasetRefreshProof").mockResolvedValue({ expiresAt: "2026-08-14T08:00:00Z", proof: "test-only" });
  const receipt: client.DatasetRefreshOperation = {
    asOf: "2026-08-14T18:00:00+08:00", attemptCount: 1, dataThroughSession: "2026-08-14",
    failureCode: null, idempotencyKey: "market-test", kind: "dataset", phase: null, completedStages: [], lastFailureCode: null,
    lastRefreshAt: "2026-08-14T10:00:00Z", outcome: "published", status: "succeeded",
  };
  const submit = vi.spyOn(client, "submitDatasetRefresh");
  if (path === "accepted") submit.mockResolvedValue(receipt);
  else submit.mockRejectedValue(new TypeError("synthetic response loss"));
  vi.spyOn(client, "loadDatasetRefresh").mockResolvedValue(receipt);
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const fill = async (selector: string, value: string, event: string) => act(async () => {
    const input = host.querySelector<HTMLInputElement>(selector)!;
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new Event(event, { bubbles: true }));
  });
  const send = async (selector: string) => act(async () => {
    (host.querySelector(selector) ?? document.querySelector(selector))!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  try {
    await act(async () => root.render(<WorkspaceQueryProvider researcherId="operator"><OperatorDataPage /></WorkspaceQueryProvider>));
    await fill('#operator-market-as-of', "2026-08-14", "change");
    await send("form");
    expect(host.querySelector('input[autocomplete="one-time-code"]')).toBeNull();
    await send('[role="dialog"] form');
    if (path === "reconciled") {
      expect(host.textContent).toContain("Confirming submission");
      await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    }
    const trigger = host.querySelector<HTMLButtonElement>('form button[type="submit"]')!;
    expect(host.textContent).toContain("Dataset published");
    expect(trigger.disabled).toBe(false);
    expect(document.activeElement).toBe(trigger);
  } finally {
    await act(async () => root.unmount());
    host.remove();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  }
});
