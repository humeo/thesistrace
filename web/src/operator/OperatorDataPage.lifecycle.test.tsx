// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, test, vi } from "vitest";
import * as client from "./operatorMutationClient";
import { OperatorDataPage } from "./OperatorDataPage";

vi.mock("./OperatorDatasetStatus", () => ({ OperatorDatasetStatus: () => null }));
vi.mock("./OperatorFinancialRefreshPanel", () => ({ OperatorFinancialRefreshPanel: () => null }));
vi.mock("./OperatorIndustryRefreshPanel", () => ({ OperatorIndustryRefreshPanel: () => null }));

test.each(["accepted", "reconciled"])("restores Market focus after the %s receipt enables its trigger", async (path) => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  // A frame is allowed to precede the React commit that enables the trigger.
  vi.spyOn(window, "requestAnimationFrame").mockImplementation(callback => { callback(0); return 1; });
  vi.spyOn(client, "confirmMarketRefreshProof").mockResolvedValue({ expiresAt: "2026-08-14T08:00:00Z", proof: "test-only" });
  const receipt: client.MarketRefreshOperation = {
    asOf: "2026-08-14T18:00:00+08:00", attemptCount: 1, dataThroughSession: "2026-08-14",
    failureCode: null, idempotencyKey: "market-test", kind: "market", lastFailureCode: null,
    lastRefreshAt: "2026-08-14T10:00:00Z", outcome: "published", status: "succeeded",
  };
  const submit = vi.spyOn(client, "submitMarketRefresh");
  if (path === "accepted") submit.mockResolvedValue(receipt);
  else submit.mockRejectedValue(new TypeError("synthetic response loss"));
  vi.spyOn(client, "loadMarketRefresh").mockResolvedValue(receipt);
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const fill = async (selector: string, value: string, event: string) => act(async () => {
    const input = host.querySelector<HTMLInputElement>(selector)!;
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new Event(event, { bubbles: true }));
  });
  const send = async (selector: string) => act(async () => {
    host.querySelector(selector)!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  try {
    await act(async () => root.render(<OperatorDataPage />));
    await fill('input[type="date"]', "2026-08-14", "change");
    await send("form");
    await fill('input[type="password"]', "test-only", "input");
    await send("dialog form");
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
