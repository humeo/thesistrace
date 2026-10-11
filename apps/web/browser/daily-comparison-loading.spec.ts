import { expect, test } from "./workbench-fixture";
import { exampleDailyTrack } from "./fixtures/daily-track";

for (const count of [1, 5, 20]) test(`Daily comparison loads ${count} curves and reads an account on demand`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.addInitScript(() => {
    const counts = { added: 0, removed: 0 };
    const added = new WeakSet<HTMLCanvasElement>(), removed = new WeakSet<HTMLCanvasElement>();
    Object.assign(window, { dailyComparisonCanvases: counts });
    new MutationObserver(records => {
      for (const record of records) for (const [nodes, seen, field] of [
        [record.addedNodes, added, "added"], [record.removedNodes, removed, "removed"],
      ] as const) for (const node of nodes) {
        if (!(node instanceof Element)) continue;
        for (const element of [node, ...node.querySelectorAll("canvas")]) {
          if (element instanceof HTMLCanvasElement && !seen.has(element)) {
            seen.add(element); counts[field] += 1;
          }
        }
      }
    }).observe(document, { childList: true, subtree: true });
  });
  const requests: string[] = [];
  page.on("request", request => { if (new URL(request.url()).pathname.startsWith("/api/")) requests.push(request.url()); });
  const returns = Array.from({ length: 500 }, (_, index) => ({
    session: new Date(Date.UTC(2024, 0, 1 + index)).toISOString().slice(0, 10), net_return: index / 1000,
  }));
  const details = Array.from({ length: count }, (_, index) => ({
    ...exampleDailyTrack, id: `track_${index.toString(16).padStart(20, "0")}`, seed_name: `Strategy ${index + 1}`,
    origin: { ...exampleDailyTrack.origin, seed_run_id: `run_comparison_${index}` },
    observation: { ...exampleDailyTrack.observation, returns, net_return: 0.499, net_asset_value_cny: "14990" },
  }));
  const summaries = details.map(detail => ({ id: detail.id, seed_name: detail.seed_name, status: detail.status,
    seed_run_id: detail.origin.seed_run_id, result_checksum_sha256: detail.origin.result_checksum_sha256,
    origin_session: returns[0].session, strategy_session: returns.at(-1)!.session }));
  const values = {
    status: "active", phase: "waiting", strategy_session: returns.at(-1)!.session,
    observation: { session: returns.at(-1)!.session, net_asset_value_cny: "14990", net_return: 0.499,
      maximum_drawdown: 0.025, session_count: 499, returns },
    strategy: { entry_session: null, net_return: 0.1, maximum_drawdown: 0.025, returns: [] },
  };
  const fullReads: string[] = [];
  const nameReads: string[] = [];
  let comparisons = 0, bytes = 0;
  let holdList = false;
  let releaseList!: () => void;
  const listReady = new Promise<void>(resolve => { releaseList = resolve; });
  let holdDetail: string | null = null;
  let releaseDetail!: () => void;
  const detailReady = new Promise<void>(resolve => { releaseDetail = resolve; });
  await page.route("**/api/daily-tracks**", async route => {
    const url = new URL(route.request().url());
    let body: unknown;
    if (url.pathname === "/api/daily-tracks") {
      if (holdList) await listReady;
      body = { items: summaries, next_cursor: null };
    }
    else if (url.pathname === "/api/daily-tracks/comparison") {
      comparisons += 1;
      body = { items: url.searchParams.getAll("track_id").map(id => ({ id, values })) };
    } else {
      const id = url.pathname.split("/").at(-1)!;
      fullReads.push(id);
      if (holdDetail === id) await detailReady;
      body = details.find(detail => detail.id === id);
    }
    const encoded = JSON.stringify(body);
    bytes += Buffer.byteLength(encoded);
    await route.fulfill({ contentType: "application/json", body: encoded });
  });
  await page.route("**/api/research-runs/run_comparison_*", route => {
    const id = new URL(route.request().url()).pathname.split("/").at(-1)!;
    nameReads.push(id);
    return route.fulfill({ json: { name: details.find(detail => detail.origin.seed_run_id === id)!.seed_name } });
  });
  const start = Date.now();
  await page.goto("/daily-tracks");
  const rows = page.getByRole("region", { name: "Strategy comparison table" });
  await expect(rows.getByRole("row", { name: new RegExp(`Strategy ${count} `) })).toContainText("49.90%");
  await expect(page.getByRole("region", { name: "Largest holdings", exact: true })).toHaveCount(0);
  await expect(page.getByRole("figure", { name: "Strategy comparison chart" }).locator("canvas").first()).toBeVisible();
  expect(fullReads).toEqual([]);
  expect(nameReads).toEqual([]);
  expect(comparisons).toBe(1);
  const initial = { tracks: count, points: 500, fullReads: fullReads.length, comparisons, nameReads: nameReads.length,
    apiRequests: requests.length, responseBytes: bytes, readyMs: Date.now() - start,
    canvases: await page.evaluate(() => (window as typeof window & { dailyComparisonCanvases: { added: number; removed: number } }).dailyComparisonCanvases) };
  await rows.getByRole("button", { name: `Strategy ${count}`, exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("000001.SZ");
  await expect.poll(() => fullReads).toEqual([summaries.at(-1)!.id]);
  expect(comparisons).toBe(1);
  await testInfo.attach("daily-comparison-metrics", { body: JSON.stringify(initial, null, 2), contentType: "application/json" });
  console.info(`Daily comparison measurement: ${JSON.stringify(initial)}`);
  if (count === 5) {
    await expect(page.getByRole("heading", { name: `Strategy ${count}`, exact: true })).toBeVisible();
    holdDetail = summaries.at(-1)!.id;
    const revalidation = page.waitForRequest(request => new URL(request.url()).pathname === `/api/daily-tracks/${holdDetail}`);
    const revalidated = page.waitForResponse(response => new URL(response.url()).pathname === `/api/daily-tracks/${holdDetail}`);
    await page.getByRole("dialog").getByRole("link", { name: "Open strategy", exact: true }).click();
    await revalidation;
    try {
      await expect(page.getByRole("button", { name: "Manage", exact: true })).toBeVisible();
      await expect(page.getByRole("heading", { name: new RegExp(`^Strategy ${count}\\b`) })).toBeVisible();
      await expect(page.getByText("Loading DailyTrack…", { exact: true })).toHaveCount(0);
    } finally { releaseDetail(); }
    await revalidated;
  } else await page.getByRole("dialog").getByRole("button", { name: "Close", exact: true }).click();
  await page.getByRole("link", { name: "Data", exact: true }).click();
  await expect(page.locator(".data-field-table")).toBeVisible();
  holdList = true;
  const returning = page.waitForRequest(request => new URL(request.url()).pathname === "/api/daily-tracks");
  await page.getByRole("link", { name: "Daily Tracks", exact: true }).click();
  await returning;
  try {
    await expect(rows.getByRole("row", { name: new RegExp(`Strategy ${count} `) })).toContainText("49.90%");
  } finally { releaseList(); }
});
