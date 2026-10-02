import { expect, test } from "@playwright/test";
import { buildModuleProductFixture } from "./build-product-fixture";
let files: Awaited<ReturnType<typeof buildModuleProductFixture>>;
test.use({ viewport: { width: 1159, height: 964 }, timezoneId: "UTC" });
test.beforeAll(async () => {
  test.setTimeout(60_000);
  files = await buildModuleProductFixture(new URL("./fixtures/chat-timeline.tsx", import.meta.url));
});
test.beforeEach(async ({ page }) => {
  await page.route("https://chat.fixture/**", route => {
    const path = new URL(route.request().url()).pathname.slice(1) || "index.html";
    const asset = files.get(path);
    return asset ? route.fulfill(asset) : route.fulfill({ status: 404, body: "" });
  });
  await page.goto("https://chat.fixture/");
});
test("only the latest turn reads its last five distinct resources, shares duplicates and keeps earlier links", async ({ page }) => {
  const requested: string[] = [];
  let name = "Shared research";
  await page.route("https://chat.fixture/api/research-runs/*", route => {
    const id = route.request().url().split("/").at(-1)!;
    requested.push(id);
    return route.fulfill({ json: { id, name, status: "succeeded", research_kind: "factor_evaluation",
      formula_summary: "rank(close)", start_date: "2026-01-01", end_date: "2026-09-01",
      result: { factor: { horizons: Object.fromEntries(["1", "5", "20"].map(h => [h, { summary: { rank_ic: { mean: 0.125 } } }])) } },
    } });
  });
  await page.goto("https://chat.fixture/?mode=research-history");
  const oldId = "run_00000000000000000000", otherId = "run_11111111111111111111", sharedId = "run_22222222222222222222";
  const cards = page.locator('section[aria-label^="ResearchRun "]');
  await expect(cards.locator("time")).toHaveCount(6);
  const eligible = [sharedId, ...[5, 6, 7, 8].map(value => `run_${String(value).repeat(20)}`)];
  expect(requested.sort()).toEqual(eligible);
  await expect(page.getByRole("link", { name: `View research: ${oldId}`, exact: true })).toHaveAttribute("href", `/research-runs/${oldId}`);
  await expect(page.getByRole("link", { name: `View research: ${otherId}`, exact: true })).toHaveCount(1);
  await expect(page.getByRole("link", { name: "View research: run_33333333333333333333", exact: true })).toHaveAttribute("href", "/research-runs/run_33333333333333333333");
  await expect(page.getByRole("link", { name: "View research: run_44444444444444444444", exact: true })).toHaveAttribute("href", "/research-runs/run_44444444444444444444");
  const lastView = page.locator('[data-entry-id="research-last-view"]');
  await expect(lastView.locator('section[aria-label^="ResearchRun "]')).toHaveCount(4);
  await expect(lastView.getByRole("link", { name: /^View research:/ })).toHaveCount(0);
  await expect(page.getByText("Answer turn-0", { exact: true })).toHaveCount(1);
  name = "Refreshed research";
  await page.getByRole("region", { name: `ResearchRun ${sharedId}`, exact: true }).last().getByRole("button", { name: "Reload view: Shared research", exact: true }).click();
  await expect(page.getByRole("link", { name, exact: true })).toHaveCount(2);
  expect(requested.filter(id => id === sharedId)).toHaveLength(2);
  await page.getByRole("button", { name: "Load older research", exact: true }).click();
  await expect(page.getByRole("link", { name: `View research: ${oldId}`, exact: true })).toHaveCount(2);
  expect(requested).toHaveLength(6);
  await page.getByRole("button", { name: "Reopen conversation", exact: true }).click();
  await expect(cards.locator("time")).toHaveCount(6);
  expect(requested.slice(6).sort()).toEqual(eligible);
  expect(requested.filter(id => id === sharedId)).toHaveLength(3);
  expect(requested).not.toContain(oldId);
  expect(requested).not.toContain(otherId);
  await page.getByRole("button", { name: "Next research turn", exact: true }).click();
  await expect(cards.locator("time")).toHaveCount(1);
  await expect(page.getByRole("link", { name: `View research: ${sharedId}`, exact: true })).toHaveCount(3);
  await expect(page.getByRole("link", { name, exact: true })).toHaveCount(1);
  expect(requested).toHaveLength(11);
});
test("desktop messages match ChatGPT's reading width while the native scroll viewport reaches the page edge", async ({ page }) => {
  await page.setViewportSize({ width: 1552, height: 942 });
  await page.getByRole("button", { name: "Complete", exact: true }).click();
  await page.getByRole("button", { name: "Send next", exact: true }).click();
  await page.getByRole("button", { name: "Finish reply", exact: true }).click();
  const main = (await page.locator("main.quantgrove-chat").boundingBox())!;
  const scroll = (await page.locator(".ant-bubble-list-scroll-box").first().boundingBox())!;
  const reply = (await page.locator('[data-entry-id="sent-1-response"] .x-markdown').boundingBox())!;
  const sender = (await page.locator(".ant-sender").boundingBox())!;
  expect(Math.abs(scroll.x + scroll.width - main.x - main.width)).toBeLessThanOrEqual(1);
  expect(reply.width).toBe(768);
  await expect(page.locator('[data-entry-id="sent-1-response"] .x-markdown')).toHaveCSS("font-size", "16px");
  await expect(page.locator('[data-entry-id="sent-1-response"] .x-markdown')).toHaveCSS("line-height", "26px");
  const replyFont = await page.locator('[data-entry-id="sent-1-response"] .x-markdown').evaluate(element => getComputedStyle(element).fontFamily);
  expect(replyFont).not.toMatch(/Inter|Noto Sans SC/);
  expect(Math.abs(reply.x - sender.x)).toBeLessThanOrEqual(1);
  expect(Math.abs(reply.width - sender.width)).toBeLessThanOrEqual(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(page.locator('.chat-message-user .ant-bubble-content').last()).toHaveCSS("font-size", "16px");
  await expect(page.locator('.chat-message-user .ant-bubble-content').last()).toHaveCSS("line-height", "26px");
  await page.getByRole("button", { name: "Typography reply", exact: true }).click();
  const prose = page.locator('[data-entry-id="sent-1-response"] .x-markdown');
  await expect(prose.locator("strong")).toHaveCSS("font-weight", "600");
  await expect(prose.locator("h2")).toHaveCSS("font-size", "20px");
  await expect(prose.locator("h3")).toHaveCSS("font-size", "18px");
  await expect(prose.locator("h3")).toHaveCSS("line-height", "28px");
  const gaps = await prose.evaluate(element => {
    const gap = (before: Element, after: Element) => after.getBoundingClientRect().top - before.getBoundingClientRect().bottom;
    const paragraphs = element.querySelectorAll(":scope > p");
    const heading = element.querySelector("h3")!;
    const items = element.querySelectorAll("li");
    return { paragraph: gap(paragraphs[0]!, paragraphs[1]!), headingBefore: gap(paragraphs[1]!, heading),
      headingAfter: gap(heading, paragraphs[2]!), list: gap(items[0]!, items[1]!) };
  });
  expect(gaps).toEqual({ paragraph: 16, headingBefore: 16, headingAfter: 4, list: 0 });
});
test("native work disclosure folds process while preserving final research views", async ({ page }) => {
  await page.getByRole("button", { name: "Complete", exact: true }).click();
  await expect(page.locator('[data-entry-id="progress"]')).toHaveCount(0);
  await expect(page.locator('[data-entry-id="result"]')).toBeVisible();
  await expect(page.locator('[data-entry-id="other-result"]')).toBeVisible();
  await expect(page.locator('[data-entry-id="final"]')).toHaveText(/Both research tasks finished/);
  const work = page.locator(".ant-think-status-text").filter({ hasText: /^Worked for/ });
  const details = page.locator(".ant-think-content").first();
  await expect(details).toBeHidden();
  await work.click();
  await expect(page.locator('[data-entry-id="before"]')).toBeVisible();
  await details.getByText("Question answered", { exact: true }).click();
  await expect(page.getByText("Default approach", { exact: true })).toBeVisible();
  await work.click();
  await expect(details).toBeHidden();
});
test("work steps fill the reading width with native titles, content and disclosure", async ({ page }) => {
  await page.getByRole("button", { name: "Complete", exact: true }).click();
  await page.locator(".ant-think-status-text").filter({ hasText: /^Worked for/ }).click();
  const process = page.locator(".ant-think-content").first();
  await expect(process.locator(".ant-card")).toBeVisible();
  await expect(process.locator(".ant-thought-chain-box")).toHaveCount(1);
  const card = (await process.locator(".ant-card").boundingBox())!;
  const reply = (await page.locator('[data-entry-id="final"] .x-markdown').boundingBox())!;
  expect(Math.abs(card.x + card.width - reply.x - reply.width)).toBeLessThanOrEqual(1);
  expect(card.width).toBeGreaterThan(reply.width - 20);
  await expect(process.locator("button, .ant-bubble, .ant-thought-chain-node-footer, .ant-bubble-list")).toHaveCount(0);
  await expect(process.getByRole("listitem", { name: "Tool get_research_context: Completed", exact: true })).toHaveCount(1);
  const toolStep = process.getByText("Used 1 tool", { exact: true }).first();
  await toolStep.click();
  await expect(process.getByRole("listitem")).toHaveCount(0);
  await toolStep.click();
  await expect(process.getByRole("listitem")).toHaveCount(1);
  await process.getByText("Used 1 tool", { exact: true }).last().click();
  await expect(process.getByRole("listitem")).toHaveCount(2);
  const question = process.getByText("Question answered", { exact: true });
  const presentation = await question.evaluate(element => ({
    height: element.getBoundingClientRect().height,
    fontSize: getComputedStyle(element).fontSize,
    weight: getComputedStyle(element).fontWeight,
  }));
  expect(presentation).toEqual({ height: 22, fontSize: "14px", weight: "500" });
  await question.click();
  await expect(process.getByText("Which approach?", { exact: true })).toBeVisible();
  await expect(process.getByText("Default approach", { exact: true })).toBeVisible();
  await question.click();
  await expect(process.getByText("Which approach?", { exact: true })).toBeHidden();
  await expect(process.getByText("Default approach", { exact: true })).toBeHidden();
});
test("native message footers copy original text and include the requested time format", async ({ page }) => {
  await page.evaluate(() => Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async (value: string) => { (window as unknown as { copied: string }).copied = value; } } }));
  await page.getByRole("button", { name: "Complete", exact: true }).click();
  await page.getByRole("button", { name: "Send next", exact: true }).click();
  await page.getByRole("button", { name: "Finish reply", exact: true }).click();
  const user = page.locator('.chat-message-user').last();
  const reply = page.locator('[data-entry-id="sent-1-response"]');
  await page.mouse.move(0, 0);
  await expect(user.locator(".ant-bubble-footer")).toHaveCSS("opacity", "0");
  await expect(reply.locator(".ant-bubble-footer")).toHaveCSS("opacity", "0");
  const userBefore = await user.boundingBox();
  await user.hover();
  await expect(user.locator(".ant-bubble-footer")).toHaveCSS("opacity", "1");
  await expect(reply.locator(".ant-bubble-footer")).toHaveCSS("opacity", "0");
  expect(await user.boundingBox()).toEqual(userBefore);
  await user.getByRole("button", { name: "Copy message", exact: true }).click();
  await expect.poll(() => page.evaluate(() => (window as unknown as { copied: string }).copied)).toBe("Hi");
  const replyBefore = await reply.boundingBox();
  await reply.hover();
  await expect(reply.locator(".ant-bubble-footer")).toHaveCSS("opacity", "1");
  expect(await reply.boundingBox()).toEqual(replyBefore);
  await reply.getByRole("button", { name: "Copy response", exact: true }).click();
  await expect.poll(() => page.evaluate(() => (window as unknown as { copied: string }).copied)).toBe("Hello. How can I help?");
  await expect(reply.locator("time")).toHaveText("12:00 AM");
  await expect(user.locator("time")).toHaveText("12:00 AM");
  const replyCopy = (await reply.getByRole("button", { name: "Copy response", exact: true }).boundingBox())!;
  const replyText = (await reply.locator(".x-markdown").boundingBox())!;
  const replyTime = (await reply.locator("time").boundingBox())!;
  expect(Math.abs(replyCopy.x - replyText.x)).toBeLessThanOrEqual(1);
  expect(Math.abs(replyCopy.y + replyCopy.height / 2 - replyTime.y - replyTime.height / 2)).toBeLessThanOrEqual(1);
  await page.mouse.move(0, 0);
  await page.getByRole("button", { name: "Finish reply", exact: true }).focus();
  await expect(user.locator(".ant-bubble-footer")).toHaveCSS("opacity", "0");
  await expect(reply.locator(".ant-bubble-footer")).toHaveCSS("opacity", "0");
  await user.getByRole("button").focus();
  await expect(user.getByRole("button")).toBeFocused();
  await expect(user.getByRole("button")).toBeVisible();
  await expect(user.locator(".ant-bubble-footer")).toHaveCSS("opacity", "1");
  await reply.getByRole("button").focus();
  await expect(reply.locator(".ant-bubble-footer")).toHaveCSS("opacity", "1");
  await expect(user.locator(".ant-bubble-footer")).toHaveCSS("opacity", "0");
});
test("plain and expandable elapsed labels share native typography with icons aligned to the reading edge", async ({ page }) => {
  await page.getByRole("button", { name: "Complete", exact: true }).click();
  await page.getByRole("button", { name: "Send next", exact: true }).click();
  await page.getByRole("button", { name: "Finish reply", exact: true }).click();
  const headings = page.locator(".ant-think-status-text").filter({ hasText: /^Worked for/ });
  expect(await headings.count()).toBe(2);
  const geometry = await headings.evaluateAll(elements => elements.map(element => ({
    x: element.closest(".ant-think")!.getBoundingClientRect().x, fontSize: getComputedStyle(element).fontSize,
    weight: getComputedStyle(element).fontWeight,
  })));
  expect(geometry[0]).toEqual(geometry[1]);
  const reply = page.locator('[data-entry-id="sent-1-response"] .x-markdown');
  expect(Math.abs((await reply.boundingBox())!.x - geometry[1]!.x)).toBeLessThanOrEqual(1);
  const gaps = await headings.evaluateAll(elements => elements.map(element => {
    const work = element.closest(".ant-bubble")!;
    const content = work.nextElementSibling!.querySelector(".ant-bubble-content")!;
    return content.getBoundingClientRect().top - work.querySelector(".ant-divider")!.getBoundingClientRect().bottom;
  }));
  // Both research views and plain replies keep the same gap after the work separator.
  expect(gaps).toEqual([16, 16]);
});
test("new prompts sit near the top with reply space and stay there through short replies", async ({ page }) => {
  await page.getByRole("button", { name: "Complete", exact: true }).click();
  await page.getByRole("button", { name: "Send next", exact: true }).click();
  const scroll = page.locator(".ant-bubble-list-scroll-box").first();
  const prompt = page.locator('.chat-message-user .ant-bubble-content').last();
  const relativeTop = async () => (await prompt.boundingBox())!.y - (await scroll.boundingBox())!.y;
  const relativePosition = async () => await relativeTop() / (await scroll.boundingBox())!.height;
  await expect.poll(relativePosition).toBeGreaterThanOrEqual(0.18);
  await expect.poll(relativePosition).toBeLessThanOrEqual(0.25);
  const position = await relativeTop();
  await page.getByRole("button", { name: "Short reply", exact: true }).click();
  await expect(page.locator('[data-entry-id="sent-1-response"]')).toContainText("Hello. How can I help?");
  await expect.poll(relativeTop).toBeCloseTo(position, 0);
  await page.getByRole("button", { name: "Finish reply", exact: true }).click();
  await expect.poll(relativeTop).toBeCloseTo(position, 0);
  await page.setViewportSize({ width: 1552, height: 942 });
  await expect.poll(relativePosition).toBeGreaterThanOrEqual(0.18);
  await expect.poll(relativePosition).toBeLessThanOrEqual(0.25);
  await page.screenshot({ path: new URL("../../../.local/ant-design-x-chat/turn-position/new-prompt.png", import.meta.url).pathname });
});
test("the first accepted prompt reserves reply space when the timeline mounts", async ({ page }) => {
  await page.goto("https://chat.fixture/?initial=prompt");
  const scroll = page.locator(".ant-bubble-list-scroll-box").first();
  const prompt = page.locator('.chat-message-user .ant-bubble-content').last();
  const relativePosition = async () => ((await prompt.boundingBox())!.y - (await scroll.boundingBox())!.y) / (await scroll.boundingBox())!.height;
  await expect.poll(relativePosition).toBeGreaterThanOrEqual(0.18);
  await expect.poll(relativePosition).toBeLessThanOrEqual(0.25);
});
test("loading completed history retains the latest position without a reply spacer", async ({ page }) => {
  await page.goto("https://chat.fixture/?initial=history");
  await page.getByRole("button", { name: "Load history", exact: true }).click();
  const scroll = page.locator(".ant-bubble-list-scroll-box").first();
  const reply = page.locator('[data-entry-id="sent-1-response"]');
  await expect(reply).toBeVisible();
  const bottomGap = async () => {
    const viewport = (await scroll.boundingBox())!;
    const message = (await reply.boundingBox())!;
    return viewport.y + viewport.height - message.y - message.height;
  };
  await expect.poll(bottomGap).toBeLessThanOrEqual(16);
});
test("sending while reading older content brings only the new prompt into the upper reading area", async ({ page }) => {
  await page.getByRole("button", { name: "Complete", exact: true }).click();
  await page.getByRole("button", { name: "Send next", exact: true }).click();
  await page.getByRole("button", { name: "Long reply", exact: true }).click();
  const scroll = page.locator(".ant-bubble-list-scroll-box").first();
  await scroll.hover();
  await page.mouse.wheel(0, -800);
  await expect.poll(() => scroll.evaluate(element => -element.scrollTop)).toBeGreaterThan(100);
  await page.getByRole("button", { name: "Send next", exact: true }).click();
  const prompt = page.locator('.chat-message-user .ant-bubble-content').last();
  const relativePosition = async () => ((await prompt.boundingBox())!.y - (await scroll.boundingBox())!.y) / (await scroll.boundingBox())!.height;
  await expect.poll(relativePosition).toBeLessThanOrEqual(0.25);
  await expect.poll(relativePosition).toBeGreaterThanOrEqual(0.18);
});
test("native scrolling preserves an upward reading position during streaming", async ({ page }) => {
  await page.getByRole("button", { name: "Complete", exact: true }).click();
  await page.getByRole("button", { name: "Send next", exact: true }).click();
  await page.getByRole("button", { name: "Long reply", exact: true }).click();
  const scroll = page.locator(".ant-bubble-list-scroll-box").first();
  await expect(scroll).toBeVisible();
  await expect(page.locator('[data-entry-id="sent-1-response"]')).toContainText("A longer streamed paragraph.");
  await scroll.hover(); await page.mouse.wheel(0, -800);
  await expect.poll(() => scroll.evaluate(element => -element.scrollTop)).toBeGreaterThan(100);
  // Native Bubble.List uses reverse scrolling: added content changes scrollTop,
  // while the paragraph being read must stay at the same screen position.
  const anchor = page.locator('[data-entry-id="sent-1-response"] .x-markdown p').first();
  const position = (await anchor.boundingBox())!.y;
  await page.getByRole("button", { name: "Long reply", exact: true }).click();
  await expect.poll(async () => (await anchor.boundingBox())!.y).toBeCloseTo(position, 0);
});
test("native Markdown retains CJK formatting and the product link boundary", async ({ page }) => {
  await page.getByRole("button", { name: "Complete", exact: true }).click();
  await page.getByRole("button", { name: "Send next", exact: true }).click();
  await page.getByRole("button", { name: "CJK reply", exact: true }).click();
  await expect(page.locator('[data-entry-id="sent-1-response"] strong')).toHaveText("数据截至：");
  await expect(page.locator('[data-entry-id="sent-1-response"] code')).toHaveText("**原文：**保持");
  await page.getByRole("button", { name: "Run link reply", exact: true }).click();
  await expect(page.getByRole("link", { name: /^X/ })).toHaveAttribute("href", "/research-runs/run_0123456789abcdef0123");
  await expect(page.getByRole("link", { name: /^X/ })).toHaveCSS("font-size", "16px");
});
