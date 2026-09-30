// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, test, vi } from "vitest";
import * as client from "./operatorMutationClient";
import { useDataRefresh } from "./useDataRefresh";

const request = { asOf: "2026-08-14T18:00:00+08:00", idempotencyKey: "market-exact" };
const receipt: client.MarketRefreshOperation = { ...request, kind: "market", attemptCount: 0, status: "accepted", outcome: null,
  dataThroughSession: null, failureCode: null, lastFailureCode: null, lastRefreshAt: null };
const complete: client.MarketRefreshOperation = { ...receipt, status: "succeeded", outcome: "published", dataThroughSession: "2026-08-14" };
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}
const cleanups: (() => Promise<void>)[] = [];
afterEach(async () => { for (const cleanup of cleanups.splice(0)) await cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); vi.unstubAllGlobals(); });
async function mount() {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  vi.spyOn(client, "confirmMarketRefreshProof").mockResolvedValue({ proof: "fresh-proof", expiresAt: "2026-08-14T10:00:00Z" });
  const accepted = vi.fn();
  const callbacks = { onAccessNotFound: vi.fn(), onOperationAccepted: accepted };
  let current!: ReturnType<typeof useDataRefresh<"market">>;
  function Harness() { current = useDataRefresh("market", callbacks); return null; }
  const host = document.createElement("div"); const root = createRoot(host);
  await act(async () => root.render(<Harness />));
  let mounted = true;
  const unmount = async () => {
    if (!mounted) return;
    mounted = false;
    await act(async () => root.unmount()); host.remove();
  };
  cleanups.push(unmount);
  return { state: () => current, accepted, unmount };
}

test("dismissed proof cannot submit even when its ignored abort resolves late", async () => {
  const view = await mount();
  const proof = deferred<{ proof: string; expiresAt: string }>();
  vi.mocked(client.confirmMarketRefreshProof).mockReturnValue(proof.promise);
  const submit = vi.spyOn(client, "submitMarketRefresh");
  await act(async () => view.state().review(request));
  await act(async () => { void view.state().confirm(); });
  await act(async () => view.state().dismissConfirmation());
  await act(async () => proof.resolve({ proof: "late", expiresAt: "2026-08-14T10:00:00Z" }));
  expect(submit).not.toHaveBeenCalled();
  expect(view.state().pendingRequest).toBeNull();
});

test("receipt reconciliation fences a late POST and allows another confirmation immediately", async () => {
  const view = await mount();
  const post = deferred<client.MarketRefreshOperation>();
  vi.spyOn(client, "submitMarketRefresh").mockReturnValue(post.promise);
  vi.spyOn(client, "loadMarketRefresh").mockResolvedValue(complete);
  await act(async () => view.state().review(request));
  await act(async () => { void view.state().confirm(); });
  await act(async () => view.state().dismissConfirmation());
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(view.state().operation?.status).toBe("succeeded");
  await act(async () => view.state().review({ ...request, idempotencyKey: "market-next" }));
  expect(view.state().operation?.status).toBe("succeeded");
  await act(async () => post.resolve(receipt));
  expect(view.state().operation?.status).toBe("succeeded");
  expect(view.state().confirmation?.request.idempotencyKey).toBe("market-next");
});

test("reviewing a new request does not fence the previous accepted operation", async () => {
  const view = await mount();
  vi.spyOn(client, "submitMarketRefresh").mockResolvedValue(receipt);
  const poll = deferred<client.MarketRefreshOperation>();
  vi.spyOn(client, "loadMarketRefresh").mockReturnValue(poll.promise);
  await act(async () => view.state().review(request));
  await act(async () => view.state().confirm());
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  await act(async () => view.state().review({ ...request, idempotencyKey: "market-next" }));
  await act(async () => poll.resolve(complete));
  expect(view.state().operation?.status).toBe("succeeded");
  expect(view.state().confirmation?.request.idempotencyKey).toBe("market-next");
});

test("exact retry takes fresh proof and stop checking isolates all earlier completions", async () => {
  const view = await mount();
  const first = deferred<client.MarketRefreshOperation>();
  vi.spyOn(client, "submitMarketRefresh").mockReturnValueOnce(first.promise).mockRejectedValueOnce(new TypeError("response lost"));
  const poll = deferred<client.MarketRefreshOperation>();
  vi.spyOn(client, "loadMarketRefresh").mockReturnValue(poll.promise);
  await act(async () => view.state().review(request));
  await act(async () => { void view.state().confirm(); });
  await act(async () => view.state().dismissConfirmation());
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  await act(async () => view.state().retryExact());
  expect(view.state().confirmation?.request).toEqual(request);
  await act(async () => view.state().confirm());
  expect(client.confirmMarketRefreshProof).toHaveBeenLastCalledWith(request, expect.any(AbortSignal));
  expect(view.state().pendingRequest).toEqual(request);
  await act(async () => view.state().stopChecking());
  await act(async () => { first.resolve(receipt); poll.resolve(complete); });
  expect(view.state().pendingRequest).toBeNull();
  expect(view.state().operation).toBeNull();
  expect(view.state().submissionFailure?.kind).toBe("stopped");
  expect(view.accepted).not.toHaveBeenCalled();
});

test.each(["stop", "retry"] as const)("%s receipt checks keeps an already submitted mutation alive and fences its receipt", async action => {
  const view = await mount();
  const post = deferred<client.MarketRefreshOperation>();
  let submittedSignal!: AbortSignal;
  vi.spyOn(client, "submitMarketRefresh").mockImplementation((_request, _proof, signal) => {
    submittedSignal = signal!;
    return post.promise;
  });
  await act(async () => view.state().review(request));
  await act(async () => { void view.state().confirm(); });
  await act(async () => view.state().dismissConfirmation());
  await act(async () => action === "stop" ? view.state().stopChecking() : view.state().retryExact());
  expect(submittedSignal.aborted).toBe(false);
  await act(async () => post.resolve(complete));
  expect(view.state().operation).toBeNull();
  expect(view.state().pendingRequest).toBeNull();
  if (action === "stop") expect(view.state().submissionFailure?.kind).toBe("stopped");
  else expect(view.state().confirmation?.request).toEqual(request);
});

test("unmounting receipt checks leaves a dismissed submission alive without accepting its late receipt", async () => {
  const view = await mount();
  const post = deferred<client.MarketRefreshOperation>();
  let submittedSignal!: AbortSignal;
  vi.spyOn(client, "submitMarketRefresh").mockImplementation((_request, _proof, signal) => {
    submittedSignal = signal!;
    return post.promise;
  });
  await act(async () => view.state().review(request));
  await act(async () => { void view.state().confirm(); });
  await act(async () => view.state().dismissConfirmation());
  await view.unmount();
  expect(submittedSignal.aborted).toBe(false);
  await act(async () => post.resolve(complete));
  expect(view.accepted).not.toHaveBeenCalled();
});
