import { expect, test } from "@playwright/test";
import { buildProductFixture } from "./build-product-fixture";
import { comparisonValues, exampleDailyTrack } from "./fixtures/daily-track";

let script: string;
let styles: string;
test.beforeAll(async () => {
  test.setTimeout(120_000);
  ({ script, styles } = await buildProductFixture(new URL("./fixtures/daily-tracks-language.tsx", import.meta.url), "DailyBulk"));
});

test("updates a strategy directly from the list and observes its published result", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  const track = structuredClone(exampleDailyTrack);
  track.seed_name = "Momentum";
  let queued = false;
  let complete = false;
  const commands: unknown[] = [];
  await page.route("https://daily-bulk.test/**", route => {
    const url = new URL(route.request().url());
    if (url.pathname === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    if (url.pathname.endsWith("/refresh")) {
      commands.push(route.request().postDataJSON());
      queued = true;
      return route.fulfill({ status: 202, json: { id: track.id, status: "active" } });
    }
    const current = { ...track, strategy_session: complete ? "2026-08-21" : track.strategy_session,
      lag_sessions: complete ? 0 : 1,
      progress: { ...track.progress, phase: complete ? "up_to_date" : queued ? "queued" : "waiting" } };
    if (url.pathname === "/api/daily-tracks") return route.fulfill({ json: { items: [{ id: track.id,
      seed_name: track.seed_name, status: "active", origin_session: "2026-08-01", strategy_session: current.strategy_session }], next_cursor: null } });
    if (url.pathname === "/api/daily-tracks/comparison") return route.fulfill({ json: { items: [{ id: track.id, values: comparisonValues(current) }] } });
    return route.fulfill({ json: current });
  });
  await page.goto("https://daily-bulk.test/?list");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await page.getByRole("button", { name: "Update all strategies", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("1 queued");
  await expect(page.getByRole("row", { name: /Momentum/ })).toContainText("Updating");
  expect(commands).toHaveLength(1);
  complete = true;
  await expect(page.getByRole("row", { name: /Momentum/ })).toContainText("Up to date");
  await expect(page.getByRole("row", { name: /Momentum/ })).toContainText("2026-08-21");
  expect(commands).toHaveLength(1);
});

test("reads every list page, skips ineligible tracks and preserves partial acceptance", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  const ids = ["first", "current", "busy", "stopped", "blocked", "unconfirmed", "after", "raced", "second"];
  const tracks = ids.map(name => ({ ...structuredClone(exampleDailyTrack), id: `track_${name}`, seed_name: name }));
  tracks[1].lag_sessions = 0;
  tracks[1].progress.phase = "up_to_date";
  tracks[2].progress.phase = "calculating";
  tracks[3].status = "stopped";
  tracks[4].status = "blocked";
  const commands: string[] = [];
  const cursors: (string | null)[] = [];
  let release!: () => void;
  const accepted = new Promise<void>(resolve => { release = resolve; });
  await page.route("https://daily-bulk-pages.test/**", async route => {
    const url = new URL(route.request().url());
    if (url.pathname === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    if (url.pathname === "/api/daily-tracks") {
      const cursor = url.searchParams.get("cursor");
      cursors.push(cursor);
      const items = (cursor ? tracks.slice(-1) : tracks.slice(0, -1)).map(track => ({ id: track.id,
        status: track.status, seed_name: track.seed_name, origin_session: "2026-08-01", strategy_session: track.strategy_session }));
      return route.fulfill({ json: { items, next_cursor: cursor ? null : "page+2/=" } });
    }
    if (url.pathname === "/api/daily-tracks/comparison") return route.fulfill({ json: { items: url.searchParams.getAll("track_id").map(id => ({
      id, values: comparisonValues(tracks.find(track => track.id === id)!),
    })) } });
    const id = url.pathname.split("/")[3];
    const track = tracks.find(track => track.id === id)!;
    if (url.pathname.endsWith("/refresh")) {
      commands.push(id);
      if (id === "track_unconfirmed") return route.fulfill({ status: 503 });
      if (id === "track_raced") return route.fulfill({ status: 409 });
      if (id === "track_first") await accepted;
      track.progress.phase = "queued";
      return route.fulfill({ status: 202, json: { id, status: "active" } });
    }
    return route.fulfill({ json: track });
  });
  await page.goto("https://daily-bulk-pages.test/?list");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  const button = page.getByRole("button", { name: "Update all strategies", exact: true });
  await expect(button).toBeEnabled();
  // Two immediate events still admit only one explicit submission operation.
  await button.evaluate(element => { (element as HTMLButtonElement).click(); (element as HTMLButtonElement).click(); });
  try {
    await expect(page.getByRole("button", { name: "Queuing strategy updates…", exact: true })).toBeDisabled();
    await expect.poll(() => commands).toEqual(["track_first"]);
  } finally { release(); }
  const result = page.getByRole("status");
  await expect(result).toContainText("3 queued · 5 skipped · 1 could not be confirmed");
  await expect(result).toContainText("current · Already up to date");
  await expect(result).toContainText("busy · Already updating or stopping");
  await expect(result).toContainText("stopped · Stopped");
  await expect(result).toContainText("blocked · Update blocked");
  await expect(result).toContainText("raced · Status changed");
  await expect(result).toContainText("unconfirmed · Submission could not be confirmed");
  expect(commands).toEqual(["track_first", "track_unconfirmed", "track_after", "track_raced", "track_second"]);
  expect(cursors).toContain("page+2/=");
  await page.getByRole("button", { name: "简体中文", exact: true }).click();
  await expect(page.getByRole("button", { name: "更新全部策略", exact: true })).toBeVisible();
  await expect(result).toContainText("已排队 3 条 · 已跳过 5 条 · 未确认 1 条");
  await page.screenshot({ path: testInfo.outputPath("bulk-refresh-desktop.png"), fullPage: true });
});

test("does not submit any commands if a remaining list page is unavailable", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  const commands: string[] = [];
  await page.route("https://daily-bulk-list-error.test/**", route => {
    const url = new URL(route.request().url());
    if (url.pathname === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    if (url.pathname.endsWith("/refresh")) { commands.push(url.pathname); return route.fulfill({ status: 202 }); }
    if (url.pathname === "/api/daily-tracks") return url.searchParams.has("cursor") ? route.fulfill({ status: 503 })
      : route.fulfill({ json: { items: [{ id: exampleDailyTrack.id, status: "active", seed_name: "Momentum" }], next_cursor: "second" } });
    if (url.pathname === "/api/daily-tracks/comparison") return route.fulfill({ json: { items: [{ id: exampleDailyTrack.id, values: comparisonValues() }] } });
    return route.fulfill({ json: exampleDailyTrack });
  });
  await page.goto("https://daily-bulk-list-error.test/?list");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await page.getByRole("button", { name: "Update all strategies", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Could not load all tracks");
  await expect(page.getByRole("button", { name: "Update all strategies", exact: true })).toBeEnabled();
  expect(commands).toEqual([]);
});

test("puts the return chart before strategy progress and opens holdings and update details only on demand", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  const track = { ...structuredClone(exampleDailyTrack), seed_name: "Momentum", lag_sessions: 0 };
  track.progress.phase = "up_to_date";
  let details = 0;
  let commands = 0;
  await page.route("https://daily-overview.test/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    if (route.request().method() !== "GET") { commands++; return route.fulfill({ status: 503 }); }
    if (path === "/api/daily-tracks") return route.fulfill({ json: { items: [{
      id: track.id, seed_name: track.seed_name, status: track.status,
      origin_session: "2026-08-01", strategy_session: track.strategy_session,
    }], next_cursor: null } });
    if (path === "/api/daily-tracks/comparison") return route.fulfill({ json: {
      items: [{ id: track.id, values: comparisonValues(track) }],
    } });
    details++;
    return route.fulfill({ json: track });
  });
  await page.goto("https://daily-overview.test/?list");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  const rows = page.getByRole("region", { name: "Strategy comparison table" });
  const chart = page.getByRole("figure", { name: "Strategy comparison chart" });
  await expect(rows).toContainText("Up to date");
  expect((await rows.boundingBox())!.y).toBeGreaterThan((await chart.boundingBox())!.y);
  await expect(rows).not.toContainText("tracked sessions");
  await expect(page.getByText("Returns start at each tracking date.", { exact: false })).toHaveCount(0);
  await expect(page.getByText("Toggle a strategy to show or hide its curve.", { exact: false })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Largest holdings", exact: true })).toHaveCount(0);
  expect(details).toBe(0);
  const preview = rows.getByRole("button", { name: "Momentum", exact: true });
  await preview.click();
  const drawer = page.getByRole("dialog");
  await expect(drawer).toContainText("000001.SZ");
  expect(details).toBe(1);
  await page.getByRole("button", { name: "简体中文", exact: true, includeHidden: true }).evaluate(element => (element as HTMLButtonElement).click());
  await expect(drawer).toContainText("最近发布的模拟账户");
  expect(details).toBe(1);
  await drawer.getByRole("button", { name: "关闭", exact: true }).press("Escape");
  await expect(drawer).toHaveCount(0);
  await expect(page.getByRole("region", { name: "策略比较表" }).getByRole("button", { name: "Momentum", exact: true })).toBeFocused();
  await page.getByRole("button", { name: "English", exact: true }).click();
  await page.getByRole("button", { name: "Update all strategies", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("0 queued · 1 skipped");
  await expect(page.getByText("Momentum · Already up to date", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Update details", exact: true }).click();
  await expect(page.getByText("Momentum · Already up to date", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "简体中文", exact: true }).click();
  await expect(page.getByRole("button", { name: "更新结果", exact: true })).toHaveAttribute("aria-expanded", "true");
  expect(commands).toBe(0);
});

test("keeps only the selected downgraded slot when updating all strategies",async({page})=>{
 await page.setViewportSize({width:1440,height:960});
 const tracks=['first','second'].map(name=>({...structuredClone(exampleDailyTrack),id:`track_${name}`,seed_name:name,lag_sessions:1}));
 let selected:string[]|null=null;
 const admitted:string[]=[];
 await page.route('https://daily-quota.test/**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path==='/')return route.fulfill({contentType:'text/html',body:'<div id="root"></div>'});
  if(path==='/api/daily-tracks')return route.fulfill({json:{items:tracks.map(track=>({id:track.id,seed_name:track.seed_name,status:track.status,origin_session:"2026-08-01",strategy_session:track.strategy_session})),next_cursor:null}});
  if(path==='/api/daily-tracks/comparison')return route.fulfill({json:{items:tracks.map(track=>({id:track.id,values:comparisonValues(track)}))}});
  const id=path.split('/')[3];const track=tracks.find(item=>item.id===id)!;
  if(path.endsWith('/refresh')){
   const body=route.request().postDataJSON();
   if(body.selected_track_ids)selected=body.selected_track_ids;
   if(!selected)return route.fulfill({status:409,json:{detail:{code:'TRACK_SELECTION_REQUIRED',limit:1,selected_track_ids:tracks.map(item=>item.id)}}});
   if(!selected.includes(id))return route.fulfill({status:409,json:{detail:{code:'TRACK_NOT_SELECTED',limit:1,selected_track_ids:selected}}});
   admitted.push(id);track.progress.phase='queued';
   return route.fulfill({status:202,json:{id,status:'active'}});
  }
  return route.fulfill({json:track});
 });
 await page.goto('https://daily-quota.test/?list');await page.addStyleTag({content:styles});await page.addScriptTag({content:script});
 await page.getByRole('button',{name:'Update all strategies',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'Choose tracks to continue'});
 await expect(dialog).toContainText('Stop is permanent');
 await dialog.getByRole('checkbox',{name:'second',exact:true}).check();
 await dialog.getByRole('button',{name:'Keep selection and continue',exact:true}).click();
 await expect(page.getByRole('status')).toContainText('1 queued');
 expect(admitted).toEqual(['track_second']);expect(selected).toEqual(['track_second']);
});
