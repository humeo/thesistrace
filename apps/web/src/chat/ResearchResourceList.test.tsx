// @vitest-environment happy-dom
import { WorkspaceQueryProvider } from "../shell/WorkspaceQueryProvider";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { notifyManager } from "@tanstack/react-query";
import { ResearchResourceList } from "./ResearchResourceList";
import { ResearchResourceProvider } from "./ResearchResourceProvider";
const request = vi.hoisted(() => vi.fn());
vi.mock("../auth/coreFetch", () => ({ coreFetch: request }));
(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
beforeEach(() => notifyManager.setNotifyFunction(callback => { act(callback); }));
afterEach(async () => { if (root) await act(async () => root.unmount()); notifyManager.setNotifyFunction(callback => callback()); document.body.replaceChildren(); vi.useRealTimers(); vi.resetAllMocks(); });
const first = "run_0123456789abcdef0123", second = "run_1123456789abcdef0123";
function run(id = first) { return { id, name: "Authoritative name", status: "succeeded", formula_summary: "rank(close)", start_date: "2026-01-01", end_date: "2026-08-27", research_kind: "factor_evaluation", result: { factor: { horizons: Object.fromEntries(["1", "5", "20"].map(h => [h, { summary: { rank_ic: { mean: 0.125 } } }])) } } }; }
async function mount(ids: string[]) { root = createRoot(document.body.appendChild(document.createElement("div"))); await act(async () => root.render(<WorkspaceQueryProvider researcherId="research-fixture"><ResearchResourceProvider><ResearchResourceList kind="run" ids={ids} /></ResearchResourceProvider></WorkspaceQueryProvider>)); }
test("loads authoritative metrics and keeps ordered failures isolated", async () => {
  request.mockImplementation((url: string) => Promise.resolve(url.endsWith(first) ? new Response(JSON.stringify(run())) : new Response(null, { status: 404 })));
  await mount([second, first]);
  await vi.waitFor(() => expect(document.body.textContent).toContain("0.125"));
  expect(document.body.textContent).toContain("Resource unavailable or access denied");
  expect([...document.querySelectorAll('section')].map(el => el.getAttribute('aria-label'))).toEqual([`ResearchRun ${second}`, `ResearchRun ${first}`]);
  expect(document.body.textContent).toContain("rank(close)");
  expect(request.mock.calls.every(([url]) => String(url).startsWith("/api/research-runs/run_"))).toBe(true);
});
test("retained reads stay isolated by conversation and Researcher", async () => {
  root = createRoot(document.body.appendChild(document.createElement("div")));
  const show = async (researcherId: string, conversationId: string) => act(async () => root.render(
    <WorkspaceQueryProvider researcherId={researcherId}>
      <ResearchResourceProvider key={conversationId} conversationId={conversationId}>
        <ResearchResourceList kind="run" ids={[first]} />
      </ResearchResourceProvider>
    </WorkspaceQueryProvider>,
  ));
  request.mockResolvedValueOnce(new Response(JSON.stringify(run())));
  await show("researcher-a", "chat-a");
  await vi.waitFor(() => expect(document.body.textContent).toContain("Authoritative name"));
  request.mockImplementation(() => new Promise(() => {}));
  await show("researcher-a", "chat-b");
  expect(document.body.textContent).not.toContain("Authoritative name");
  await show("researcher-a", "chat-a");
  expect(document.body.textContent).toContain("Authoritative name");
  expect(document.body.textContent).not.toContain("Loading research data");
  await show("researcher-b", "chat-a");
  expect(document.body.textContent).not.toContain("Authoritative name");
});
test("reopening reuses terminal reads for thirty seconds from the actual read and still allows manual refresh", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-09T08:00:00Z"));
  root = createRoot(document.body.appendChild(document.createElement("div")));
  const show = async (conversationId: string) => act(async () => root.render(
    <WorkspaceQueryProvider researcherId="researcher-a">
      <ResearchResourceProvider key={conversationId} conversationId={conversationId}>
        <ResearchResourceList kind="run" ids={conversationId === "chat-a" ? [first] : []} />
      </ResearchResourceProvider>
    </WorkspaceQueryProvider>,
  ));
  let name = "Authoritative name";
  request.mockImplementation(async () => new Response(JSON.stringify({ ...run(), name })));
  await show("chat-a");
  await vi.waitFor(() => expect(document.querySelector("time")).not.toBeNull());
  const readAt = document.querySelector("time")!.getAttribute("datetime")!;
  for (const age of [10_000, 29_999]) {
    await show("chat-b");
    vi.setSystemTime(new Date(Date.parse(readAt) + age));
    await show("chat-a");
    expect(request).toHaveBeenCalledTimes(1);
    expect(document.querySelector("time")!.getAttribute("datetime")).toBe(readAt);
    expect(document.body.textContent).not.toContain("Loading research data");
  }

  await show("chat-b");
  vi.setSystemTime(new Date(Date.parse(readAt) + 30_000));
  name = "Current research name";
  await show("chat-a");
  await vi.waitFor(() => expect(document.body.textContent).toContain(name));
  expect(request).toHaveBeenCalledTimes(2);
  const refreshedAt = document.querySelector("time")!.getAttribute("datetime")!;
  expect(refreshedAt).not.toBe(readAt);

  vi.setSystemTime(new Date(Date.parse(refreshedAt) + 1_000));
  name = "Manually refreshed name";
  await act(async () => document.querySelector("button")!.click());
  await vi.waitFor(() => expect(document.body.textContent).toContain(name));
  expect(request).toHaveBeenCalledTimes(3);
  expect(document.querySelector("time")!.getAttribute("datetime")).not.toBe(refreshedAt);
});
test.each(["running", "unavailable", "transient"])("reopening retries a %s read even within the fresh-cache window", async state => {
  vi.useFakeTimers();
  root = createRoot(document.body.appendChild(document.createElement("div")));
  const show = async (conversationId: string) => act(async () => root.render(
    <WorkspaceQueryProvider researcherId="researcher-a">
      <ResearchResourceProvider key={conversationId} conversationId={conversationId}>
        <ResearchResourceList kind="run" ids={conversationId === "chat-a" ? [first] : []} />
      </ResearchResourceProvider>
    </WorkspaceQueryProvider>,
  ));
  request.mockResolvedValueOnce(state === "unavailable"
    ? new Response(null, { status: 403 })
    : new Response(JSON.stringify({ ...run(), status: state === "running" ? "running" : "succeeded" })));
  await show("chat-a");
  await vi.waitFor(() => expect(document.querySelector('button')?.getAttribute('aria-busy')).toBe("false"));
  if (state === "transient") {
    request.mockResolvedValueOnce(new Response(null, { status: 503 }));
    await act(async () => document.querySelector("button")!.click());
    await vi.waitFor(() => expect(document.querySelector('[role="alert"]')).not.toBeNull());
    expect(document.body.textContent).toContain("Authoritative name");
  }
  await show("chat-b");
  request.mockResolvedValueOnce(new Response(JSON.stringify({ ...run(), name: "Current completed research" })));
  await show("chat-a");
  await vi.waitFor(() => expect(document.body.textContent).toContain("Current completed research"));
  expect(document.body.textContent).toContain("0.125");
  expect(document.querySelector('[role="alert"]')).toBeNull();
  expect(request).toHaveBeenCalledTimes(state === "transient" ? 3 : 2);
});
test("rejects mismatched resource identity and supports an explicit retry", async () => {
  request.mockResolvedValueOnce(new Response(JSON.stringify(run(second)))).mockResolvedValueOnce(new Response(JSON.stringify(run())));
  await mount([first]);
  await vi.waitFor(() => expect(document.body.textContent).toContain("identity mismatch"));
  expect(document.body.textContent).not.toContain("0.125");
  await act(async () => document.querySelector('button')!.click());
  await vi.waitFor(() => expect(document.body.textContent).toContain("0.125"));
});
test("changing resource aborts the old load and cannot show its late response", async () => {
  let resolve!: (response: Response) => void;
  request.mockImplementationOnce(() => new Promise<Response>(r => { resolve = r; })).mockResolvedValueOnce(new Response(JSON.stringify({ ...run(second), name: "Second research" })));
  await mount([first]);
  const signal = request.mock.calls[0][1].signal as AbortSignal;
  await act(async () => root.render(<WorkspaceQueryProvider researcherId="research-fixture"><ResearchResourceProvider><ResearchResourceList kind="run" ids={[second]} /></ResearchResourceProvider></WorkspaceQueryProvider>));
  expect(signal.aborted).toBe(true);
  await act(async () => resolve(new Response(JSON.stringify(run()))));
  await vi.waitFor(() => expect(document.body.textContent).toContain("Second research"));
  expect(document.body.textContent).not.toContain("Authoritative name");
});
test("reads DailyTrack observation and reports blocked state from Core", async () => {
  const id = "track_0123456789abcdef0123";
  request.mockResolvedValue(new Response(JSON.stringify({ id, status: "blocked", origin: { seed_run_id: first, strategy_session: "2026-08-20" }, strategy_session: "2026-08-27", data_through_session: "2026-08-26", blocked_reason: "Required data is pending", blocked_code: "FINANCIAL_COVERAGE_UNAVAILABLE", observation: { session: "2026-08-27", net_return: 0.125, maximum_drawdown: -0.025 } })));
  root = createRoot(document.body.appendChild(document.createElement("div")));
  await act(async () => root.render(<WorkspaceQueryProvider researcherId="research-fixture"><ResearchResourceProvider><ResearchResourceList kind="track" ids={[id]} /></ResearchResourceProvider></WorkspaceQueryProvider>));
  await vi.waitFor(() => expect(document.body.textContent).toContain("Financial Coverage ends before the next Research Session."));
  expect(document.body.textContent).not.toContain("Required data is pending");
  expect(document.body.textContent).toContain("12.50%");
  expect(document.body.textContent).toContain("-2.50%");
  expect(request.mock.calls[0][0]).toBe(`/api/daily-tracks/${id}`);
});
test("requires strategy results and renders them without Factor evidence", async () => {
  const strategy = {
    ...run(), research_kind: "strategy_backtest",
    result: { strategy: { summary: { metrics: {
      annualized_excess_return: 0.2, sharpe: null, maximum_drawdown: { value: -0.12 },
    } } } },
  };
  request.mockResolvedValueOnce(new Response(JSON.stringify({ ...strategy, result: undefined })))
    .mockResolvedValueOnce(new Response(JSON.stringify(strategy)));
  await mount([first]);
  await vi.waitFor(() => expect(document.body.textContent).toContain("Completed research result is unavailable"));
  await act(async () => document.querySelector('button')!.click());
  await vi.waitFor(() => expect(document.body.textContent).toContain("20.00%"));
  expect(document.body.textContent).toContain("-12.00%");
  expect(document.body.textContent).toContain("—");
  expect(document.querySelector('[aria-label="Not available"]')?.textContent).toBe("—");
  expect(document.body.textContent).not.toContain("Rank IC");
});

test("transient refresh failure preserves prior facts and their read time", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-04T11:13:38.752Z"));
  request.mockResolvedValueOnce(new Response(JSON.stringify(run())))
    .mockResolvedValueOnce(new Response(null, { status: 503 }));
  await mount([first]);
  await vi.waitFor(() => expect(document.querySelector("time")).not.toBeNull());
  const readTime = document.querySelector("time")?.getAttribute("datetime");
  const readLabel = document.querySelector("time")?.textContent;
  expect(readLabel).toMatch(/^Read \d{2}\/\d{2}\/2026,/);
  vi.setSystemTime(new Date("2026-10-05T11:13:38.752Z"));
  await act(async () => document.querySelector('button')!.click());
  await vi.waitFor(() => expect(document.querySelector('[role="alert"]')).not.toBeNull());
  expect(document.body.textContent).toContain("0.125");
  expect(document.querySelector("time")?.getAttribute("datetime")).toBe(readTime);
  expect(document.querySelector("time")?.textContent).toBe(readLabel);
});

test.each([403, 404])("refresh %s removes facts that are no longer accessible", async status => {
  request.mockResolvedValueOnce(new Response(JSON.stringify(run()))).mockResolvedValueOnce(new Response(null, { status }));
  await mount([first]);
  await vi.waitFor(() => expect(document.body.textContent).toContain("0.125"));
  await act(async () => document.querySelector('button')!.click());
  await vi.waitFor(() => expect(document.body.textContent).toContain("Resource unavailable or access denied"));
  expect(document.body.textContent).not.toContain("0.125");
  expect(document.querySelector("time")).toBeNull();
  request.mockResolvedValueOnce(new Response(null, { status: 503 }));
  await act(async () => document.querySelector('button')!.click());
  await vi.waitFor(() => expect(document.body.textContent).toContain("Research data could not be loaded"));
  expect(document.body.textContent).not.toContain("0.125");
  expect(document.querySelector("time")).toBeNull();
});

test("malformed JSON on refresh clears the last facts as an invalid response", async () => {
  request.mockResolvedValueOnce(new Response(JSON.stringify(run()))).mockResolvedValueOnce(new Response("{broken"));
  await mount([first]);
  await vi.waitFor(() => expect(document.body.textContent).toContain("0.125"));
  await act(async () => document.querySelector('button')!.click());
  await vi.waitFor(() => expect(document.body.textContent).toContain("Research response is invalid"));
  expect(document.body.textContent).not.toContain("0.125");
  expect(document.querySelector("time")).toBeNull();
});

test("a slow successful read can finish beyond five seconds", async () => {
  vi.useFakeTimers();
  let finish!: (response: Response) => void;
  request.mockImplementationOnce(() => new Promise<Response>(resolve => { finish = resolve; }));
  await mount([first]);
  await act(async () => { await vi.advanceTimersByTimeAsync(7_000); });
  expect(document.querySelector('[role="status"]')).not.toBeNull();
  expect(document.querySelector('[role="alert"]')).toBeNull();
  await act(async () => finish(new Response(JSON.stringify(run()))));
  await vi.waitFor(() => expect(document.body.textContent).toContain("0.125"));
});

test.each(["headers", "body"])("a stalled %s request ends loading and allows a manual retry", async phase => {
  vi.useFakeTimers();
  let resolve!: (value: unknown) => void;
  const stalled = new Promise<unknown>(r => { resolve = r; });
  request.mockResolvedValueOnce(new Response(JSON.stringify(run())))
    .mockImplementationOnce(() => phase === "headers" ? stalled : Promise.resolve({ ok: true, json: () => stalled }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ...run(), name: "Retried research" })));
  await mount([first]);
  await vi.waitFor(() => expect(document.querySelector("time")).not.toBeNull());
  const readTime = document.querySelector("time")!.getAttribute("datetime");
  await act(async () => document.querySelector("button")!.click());
  await vi.waitFor(() => expect(document.querySelector("button")!.getAttribute("aria-busy")).toBe("true"));
  expect(document.querySelector('[role="status"]')).toBeNull();
  await act(async () => { await vi.advanceTimersByTimeAsync(15_001); });
  expect(document.querySelector("button")!.getAttribute("aria-busy")).toBe("false");
  expect(document.body.textContent).toContain("Research data could not be loaded");
  expect(document.body.textContent).toContain("0.125");
  expect(document.querySelector("time")!.getAttribute("datetime")).toBe(readTime);
  expect((request.mock.calls[1][1].signal as AbortSignal).aborted).toBe(true);
  await act(async () => document.querySelector("button")!.click());
  await vi.waitFor(() => expect(document.body.textContent).toContain("Retried research"));
  await act(async () => resolve(phase === "headers" ? new Response(JSON.stringify({ ...run(), name: "Late research" })) : { ...run(), name: "Late research" }));
  expect(document.body.textContent).not.toContain("Late research");
});
