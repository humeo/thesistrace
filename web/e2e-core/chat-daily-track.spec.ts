import { execFileSync } from "node:child_process";
import type { Page } from "@playwright/test";

import { expect, sameOriginHeaders, test, testProjectName } from "./auth-fixture";
import { proxyState, setProxyMode } from "./fault-proxy";
import { controlWorker } from "./research-run-control";

const startPrompt = "Start daily tracking for the successful Strategy in this Chat.";
const reloadPrompt = "Reload the DailyTrack view in this Chat and explain its current observations.";
const resumePrompt = "Resume DailyTrack from this Chat using the same MCP command.";

test("Chat DailyTrack uses the full grant and explains a real Strategy's current observations", async ({ page, researcher }, testInfo) => {
  test.setTimeout(240_000);
  const browserCoreWrites: string[] = [];
  page.on("request", (request) => {
    if (request.method() !== "GET" && /^\/api\/(research-runs|research-batches|daily-tracks)/.test(new URL(request.url()).pathname)) browserCoreWrites.push(request.method());
  });
  await page.goto("/chat");
  await send(page, "Backtest a low-volatility Alpha strategy using reliable ThesisTrace defaults.");
  await send(page, startPrompt);
  await expect(page.getByRole("article", { name: "Tool start_daily_track: Completed" })).toBeVisible();
  const surface = page.getByRole("article", { name: "Research surface" }).last();
  const link = surface.getByRole("link", { name: "Open DailyTrack", exact: true });
  const href = await link.getAttribute("href");
  if (href === null || !/^\/daily-tracks\/track_[a-f0-9]{20}$/.test(href)) throw new Error("No canonical DailyTrack navigation");
  const id = href.split("/").at(-1)!;
  const detail = await track(page, id);
  expect(detail.status).toBe("active");
  await expect(surface).toContainText(detail.origin.seed_run_id);
  await expect(surface).toContainText(`Data through ${detail.data_through_session}`);
  await assertCurrentObservation(page, detail);
  const oldText = await surface.innerText();
  const sessionUrl = page.url();
  await page.reload();
  await expect(page.getByRole("article", { name: "Research surface" }).last()).toHaveText(oldText, { useInnerText: true });
  await send(page, reloadPrompt);
  await assertCurrentObservation(page, await track(page, id));
  await send(page, startPrompt);
  await expect(page.getByRole("article", { name: "Tool start_daily_track: Completed" })).toHaveCount(1);
  expect(trackFacts(researcher.id)).toMatchObject({ tracks: 1, starts: 1, retries: 0, stops: 0 });
  await send(page, "List my recent DailyTracks.");
  await expect(page.getByRole("article", { name: "Tool list_daily_tracks: Completed" }).last()).toBeVisible();
  await send(page, "List the authenticated capabilities available in this Chat.");
  const capabilities = page.locator(".chat-message-assistant .chat-assistant-markdown").last();
  for (const name of [
    "get_research_context", "get_alpha_catalog", "diagnose_alpha_formula", "get_research_run", "get_research_run_result", "list_research_runs", "submit_research_run",
    "get_research_batch", "list_research_batches", "submit_research_batch", "list_daily_tracks", "get_daily_track", "get_daily_track_result", "start_daily_track", "retry_daily_track",
  ]) await expect(capabilities).toContainText(name);
  await expect(capabilities).not.toContainText(/stop_daily_track|cancel_research_run|cancel_research_batch/);
  await send(page, "Stop the DailyTrack in this Chat.");
  expect(trackFacts(researcher.id)).toMatchObject({ tracks: 1, starts: 1, retries: 0, stops: 0 });
  await expect(page.getByRole("button", { name: /^(Stop|Confirm|Retry)( DailyTrack)?$/ })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Conversation", exact: true })).not.toContainText(/checkpoint|lease_owner|object_key/);
  expect(browserCoreWrites).toEqual([]);
  await page.getByRole("table", { name: "Latest DailyTrack Observation", exact: true }).last().scrollIntoViewIfNeeded();
  await testInfo.attach("daily-track-desktop", { body: await page.screenshot(), contentType: "image/png" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("table", { name: "Latest DailyTrack Observation", exact: true }).last().scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await testInfo.attach("daily-track-mobile", { body: await page.screenshot(), contentType: "image/png" });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.getByRole("link", { name: "Open DailyTrack", exact: true }).last().click();
  await expect(page).toHaveURL(new RegExp(`${href}$`));
  await expect(page.locator(".research-run-facts").first()).toContainText("Status active");
  await page.goto(sessionUrl);
  await deleteChat(page);
  expect(await track(page, id)).toEqual(detail);
  expect(trackFacts(researcher.id)).toMatchObject({ tracks: 1, starts: 1, retries: 0, stops: 0 });
});

test("Chat DailyTrack replays lost Start and Retry responses while Tracking advances after Chat deletion", async ({ page, researcher }) => {
  test.setTimeout(240_000);
  const admitted = await page.request.post("/api/research-runs", {
    data: {
      request_id: `daily-track-origin-${researcher.id}`, folder_id: "folder_default",
      name: "Tracking advance fixture", formula: "rank(close)", hypothesis: null,
      start_date: "2026-08-03", end_date: "2026-08-04", universe: "top300", neutralization: "none",
      research_kind: "strategy_backtest", holdings_count: 10, rebalance_every_sessions: 1,
    }, headers: sameOriginHeaders(),
  });
  expect(admitted.status()).toBe(202);
  const runId = ((await admitted.json()) as { id: string }).id;
  await expect.poll(async () => ((await (await page.request.get(`/api/research-runs/${runId}`)).json()) as { status: string }).status, { timeout: 90_000 }).toBe("succeeded");
  controlWorker("pause", "tracking-worker");
  let paused = true;
  try {
    await page.goto("/chat");
    setProxyMode("mcp-fault-proxy", 8150, "tool-call", "disconnect-submit");
    await send(page, `Start daily tracking for ${runId}.`, "Run failed");
    await expect(page.getByRole("article", { name: "Tool start_daily_track: Failed" })).toBeVisible();
    const started = trackFacts(researcher.id);
    expect(started).toMatchObject({ starts: 1, tracks: 1, retries: 0 });
    expect(Number(proxyState("mcp-fault-proxy", 8150).disconnected_submit_responses)).toBeGreaterThanOrEqual(1);
    const id = started.track_ids[0]!;
    setProxyMode("mcp-fault-proxy", 8150, "tool-call", "pass");
    await send(page, resumePrompt);
    await assertCurrentObservation(page, await track(page, id));
    expect(trackFacts(researcher.id)).toEqual(started);
    // A real one-shot Tracking Worker rejects its frozen target at a one-byte
    // execution capacity. No SQL lifecycle fabrication or shared Data mutation.
    execFileSync("docker", [
      "exec", "--env", "THESISTRACE_TRACKING_WORKER_EXECUTION_MEMORY_BYTES=1",
      `${testProjectName()}-api-1`, "thesistrace-core-worker", "--role", "tracking", "--once",
    ], {
      stdio: "pipe", timeout: 60_000,
    });
    const blocked = await track(page, id);
    expect(blocked.status).toBe("blocked");
    expect(blocked.blocked_reason).toBe("DailyTrack target exceeds Tracking Worker capacity.");
    await send(page, reloadPrompt);
    await expect(page.getByRole("article", { name: "Research surface" }).last()).toContainText(blocked.blocked_reason!);
    setProxyMode("mcp-fault-proxy", 8150, "tool-call", "disconnect-submit");
    await send(page, "Retry the blocked DailyTrack in this Chat if it is eligible.", "Run failed");
    await expect(page.getByRole("article", { name: "Tool retry_daily_track: Failed" })).toBeVisible();
    const retryAccepted = trackFacts(researcher.id);
    expect(retryAccepted).toMatchObject({ tracks: 1, starts: 1, retries: 1, stops: 0 });
    setProxyMode("mcp-fault-proxy", 8150, "tool-call", "pass");
    await send(page, resumePrompt);
    expect(trackFacts(researcher.id)).toEqual(retryAccepted);
    expect((await track(page, id)).strategy_session).toBe("2026-08-04");
    await deleteChat(page);
    controlWorker("unpause", "tracking-worker");
    paused = false;
    await expect.poll(async () => {
      const current = await track(page, id);
      return `${current.status}:${current.strategy_session}`;
    }, { timeout: 90_000 }).toBe("active:2026-08-05");
    expect(trackFacts(researcher.id)).toEqual(retryAccepted);
    await page.goto(`/daily-tracks/${id}`);
    await expect(page.locator(".research-run-facts").first()).toContainText("Advance phase up_to_date");
  } finally {
    setProxyMode("mcp-fault-proxy", 8150, "tool-call", "pass");
    if (paused) controlWorker("unpause", "tracking-worker");
  }
});

type Track = Readonly<{
  id: string; status: string; blocked_reason: string | null; strategy_session: string; data_through_session: string;
  origin: { seed_run_id: string };
  strategy: { summary: { metrics: { sharpe: number | null } }; observations: Array<{ session: string; net_nav: string; net_cash: string; holdings_count: number; transaction_cost_cny: string }> };
}>;

async function track(page: Page, id: string): Promise<Track> {
  const response = await page.request.get(`/api/daily-tracks/${id}`);
  expect(response.status()).toBe(200);
  return await response.json() as Track;
}

async function assertCurrentObservation(page: Page, detail: Track): Promise<void> {
  const observation = detail.strategy.observations.at(-1);
  expect(observation?.session).toBe(detail.strategy_session);
  const table = page.getByRole("table", { name: "Latest DailyTrack Observation", exact: true }).last();
  await expect(table).toBeVisible();
  for (const value of [observation!.session, observation!.net_nav, observation!.net_cash, String(observation!.holdings_count), observation!.transaction_cost_cny]) {
    await expect(table).toContainText(value);
  }
  const metrics = page.getByRole("region", { name: "Current DailyTrack metrics", exact: true }).last();
  const sharpe = detail.strategy.summary.metrics.sharpe;
  await expect(metrics).toContainText(sharpe === null ? "Unavailable" : sharpe.toFixed(4));
}

async function send(page: Page, prompt: string, status = "Run complete"): Promise<void> {
  await page.getByRole("textbox", { name: "Message", exact: true }).fill(prompt);
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.locator(".chat-composer-status-row").getByRole("status")).toHaveText(status, { timeout: 90_000 });
}

async function deleteChat(page: Page): Promise<void> {
  const id = new URL(page.url()).searchParams.get("session");
  if (id === null) throw new Error("Chat deletion requires a durable Session");
  const title = (await page.locator(".chat-session-title strong").innerText()).trim();
  await page.getByRole("button", { name: `Actions for ${title}` }).click();
  await page.getByRole("menuitem", { name: "Delete Chat" }).click();
  await page.getByRole("dialog", { name: "Delete Chat?" }).getByRole("button", { name: "Delete Chat" }).click();
  await expect(page).toHaveURL(/\/chat$/);
  expect((await page.request.get(`/api/agent/sessions/${id}`, { headers: sameOriginHeaders() })).status()).toBe(404);
}

type TrackFacts = Readonly<{ tracks: number; starts: number; retries: number; stops: number; track_ids: string[]; start_requests: string[]; retry_requests: string[] | null }>;
function trackFacts(researcherId: string): TrackFacts {
  if (!/^[0-9a-f-]{36}$/.test(researcherId)) throw new Error("Track inspection requires a safe Researcher ID");
  return JSON.parse(execFileSync("docker", [
    "exec", "--env", "PGPASSWORD=owner-test-password", `${testProjectName()}-postgres-1`,
    "psql", "--username", "thesistrace_owner", "--dbname", "thesistrace", "--tuples-only", "--no-align", "--set", "ON_ERROR_STOP=1", "--command", `
      SELECT json_build_object(
        'tracks', count(*), 'track_ids', json_agg(id ORDER BY id),
        'starts', (SELECT count(*) FROM research_runs.start_tracking_receipts WHERE researcher_id = '${researcherId}'::uuid),
        'retries', (SELECT count(*) FROM daily_tracks.retry_receipts WHERE researcher_id = '${researcherId}'::uuid),
        'stops', (SELECT count(*) FROM daily_tracks.stop_receipts WHERE researcher_id = '${researcherId}'::uuid),
        'start_requests', (SELECT json_agg(request_id ORDER BY request_id) FROM research_runs.start_tracking_receipts WHERE researcher_id = '${researcherId}'::uuid),
        'retry_requests', (SELECT json_agg(request_id ORDER BY request_id) FROM daily_tracks.retry_receipts WHERE researcher_id = '${researcherId}'::uuid)
      ) FROM daily_tracks.tracks WHERE researcher_id = '${researcherId}'::uuid
    `,
  ], { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], timeout: 10_000 }).trim()) as TrackFacts;
}
