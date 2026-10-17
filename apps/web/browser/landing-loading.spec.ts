import { expect, test } from "./workbench-fixture";

test("the landing heading and language control work while the conversation preview loads", async ({ page, bundle }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  const chatFiles = new Set([...bundle].filter(([, asset]) => asset.modules.some(id => id.includes("/@ant-design/x/"))).map(([file]) => file));
  expect(chatFiles.size).toBeGreaterThan(0);
  let release!: () => void;
  const chatAvailable = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/*.js", async route => {
    if (chatFiles.has(new URL(route.request().url()).pathname.slice(1))) await chatAvailable;
    await route.fallback();
  });
  try {
    await page.goto("/?lang=en", { waitUntil: "commit" });
    await expect(page.getByRole("heading", { name: "From an idea. To evidence." })).toBeVisible({ timeout: 3_000 });
    await page.getByRole("button", { name: "Switch to Chinese", exact: true }).click();
    await expect(page.getByRole("heading", { name: /从一个想法，\s*到可验证的研究。/ })).toBeVisible();
  } finally { release(); }
  await expect(page.locator(".qh-example-conversation .ant-bubble-list")).toBeVisible();
});

test("the landing chart loads near its section and survives a language switch", async ({ page, bundle }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  const scripts = new Set<string>();
  page.on("request", request => {
    if (request.resourceType() === "script") scripts.add(new URL(request.url()).pathname.slice(1));
  });
  await page.goto("/?lang=en");
  await expect(page.locator(".qh-example-conversation .ant-bubble-list")).toBeVisible();
  const loadedChart = () => [...scripts].some(file => bundle.get(file)?.modules.some(id => id.includes("/lightweight-charts/")));
  expect(loadedChart()).toBe(false);
  await page.locator("#tracking").scrollIntoViewIfNeeded();
  const chart = page.locator("#tracking canvas").first();
  await expect(chart).toBeVisible();
  expect(loadedChart()).toBe(true);
  const original = await chart.elementHandle();
  await page.getByRole("button", { name: "Switch to Chinese", exact: true }).click();
  expect(await original!.evaluate(element => element.isConnected)).toBe(true);
  await page.locator("#tracking").scrollIntoViewIfNeeded();
  await expect(chart).toBeVisible();
});
