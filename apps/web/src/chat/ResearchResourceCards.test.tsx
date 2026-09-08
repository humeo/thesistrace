// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, test, vi } from "vitest";
import { ResearchResourceCards } from "./ResearchResourceCards";
const request = vi.hoisted(() => vi.fn());
vi.mock("../auth/coreFetch", () => ({ coreFetch: request }));
(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
afterEach(async () => { if (root) await act(async () => root.unmount()); document.body.replaceChildren(); vi.resetAllMocks(); });
const first = "run_0123456789abcdef0123", second = "run_1123456789abcdef0123";
function run(id = first) { return { id, name: "Authoritative name", status: "succeeded", formula_summary: "rank(close)", start_date: "2026-01-01", end_date: "2026-08-27", research_kind: "factor_evaluation", result: { factor: { horizons: Object.fromEntries(["1", "5", "20"].map(h => [h, { summary: { rank_ic: { mean: 0.125 } } }])) } } }; }
async function mount(ids: string[]) { root = createRoot(document.body.appendChild(document.createElement("div"))); await act(async () => root.render(<ResearchResourceCards kind="run" ids={ids} />)); }
test("loads authoritative metrics and keeps ordered failures isolated", async () => {
  request.mockImplementation((url: string) => Promise.resolve(url.endsWith(first) ? new Response(JSON.stringify(run())) : new Response(null, { status: 404 })));
  await mount([second, first]);
  await vi.waitFor(() => expect(document.body.textContent).toContain("0.125"));
  expect(document.body.textContent).toContain("Resource unavailable or access denied");
  expect([...document.querySelectorAll('section')].map(el => el.getAttribute('aria-label'))).toEqual([`ResearchRun ${second}`, `ResearchRun ${first}`]);
  expect(document.body.textContent).toContain("rank(close)");
  expect(request.mock.calls.every(([url]) => String(url).startsWith("/api/research-runs/run_"))).toBe(true);
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
  await act(async () => root.render(<ResearchResourceCards kind="run" ids={[second]} />));
  expect(signal.aborted).toBe(true);
  await act(async () => resolve(new Response(JSON.stringify(run()))));
  await vi.waitFor(() => expect(document.body.textContent).toContain("Second research"));
  expect(document.body.textContent).not.toContain("Authoritative name");
});
test("reads DailyTrack observation and reports blocked state from Core", async () => {
  const id = "track_0123456789abcdef0123";
  request.mockResolvedValue(new Response(JSON.stringify({ id, status: "blocked", origin: { seed_run_id: first, strategy_session: "2026-08-20" }, strategy_session: "2026-08-27", data_through_session: "2026-08-26", blocked_reason: "Required data is pending", observation: { session: "2026-08-27", net_return: 0.125, maximum_drawdown: -0.025 } })));
  root = createRoot(document.body.appendChild(document.createElement("div")));
  await act(async () => root.render(<ResearchResourceCards kind="track" ids={[id]} />));
  expect(document.body.textContent).toContain("Required data is pending");
  expect(document.body.textContent).toContain("12.50%");
  expect(document.body.textContent).toContain("-2.50%");
  expect(request.mock.calls[0][0]).toBe(`/api/daily-tracks/${id}`);
});
test("requires strategy results and formats their authoritative metrics", async () => {
  request.mockResolvedValueOnce(new Response(JSON.stringify({ ...run(), research_kind: "strategy_backtest" }))).mockResolvedValueOnce(new Response(JSON.stringify({ ...run(), research_kind: "strategy_backtest", result: { ...run().result, strategy: { summary: { metrics: { annualized_excess_return: 0.2, sharpe: null, maximum_drawdown: { value: -0.12 } } } } } })));
  await mount([first]);
  expect(document.body.textContent).toContain("Completed research result is unavailable");
  await act(async () => document.querySelector('button')!.click());
  expect(document.body.textContent).toContain("20.00%");
  expect(document.body.textContent).toContain("-12.00%");
  expect(document.body.textContent).toContain("Not available");
});
