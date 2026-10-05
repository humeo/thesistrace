import { expect, test } from "@playwright/test";
import { buildModuleProductFixture } from "./build-product-fixture";

declare global {
  interface Window {
    chatPerformanceSource: { acceptedAt: number; firstChunkAt: number; finishedAt: number; timelineRequests: number; chunks: number; previewAt: number; formattedTextEndAt: number };
    chatPerformancePaint: {
      inputs: { at: number; delay: number }[];
      frames: number[];
      longTasks: number[];
      promptAt: number;
      firstReplyAt: number;
      replyPaints: { at: number; length: number }[];
      emptyChatFrames: number;
      composerReplacements: number;
      formattedPreviewAt: number;
      reorderedFrames: number;
    };
  }
}
let files: Awaited<ReturnType<typeof buildModuleProductFixture>>;
test.use({ viewport: { width: 1159, height: 964 } });
test.beforeAll(async () => {
  test.setTimeout(180_000);
  files = await buildModuleProductFixture(new URL("./fixtures/chat-performance.tsx", import.meta.url));
});
test.beforeEach(async ({ page }) => {
  await page.route("https://chat.fixture/**", route => {
    const path = new URL(route.request().url()).pathname.slice(1) || "index.html";
    const asset = files.get(path);
    return asset ? route.fulfill(asset) : route.fulfill({ status: 404 });
  });
  await page.addInitScript(() => {
    const metrics = { inputs: [] as { at: number; delay: number }[], frames: [] as number[], longTasks: [] as number[], promptAt: 0, firstReplyAt: 0,
      replyPaints: [] as { at: number; length: number }[], emptyChatFrames: 0, composerReplacements: 0, formattedPreviewAt: 0, reorderedFrames: 0 };
    Object.assign(window, { chatPerformancePaint: metrics });
    let previousFrame = 0;
    let composer: HTMLTextAreaElement | null = null;
    const frame = (now: number) => {
      if (previousFrame) metrics.frames.push(now - previousFrame);
      previousFrame = now;
      const input = document.querySelector<HTMLTextAreaElement>('textarea[aria-label="Message"]');
      if (input) {
        if (composer && composer !== input) metrics.composerReplacements++;
        composer = input;
      }
      if (window.chatPerformanceSource?.acceptedAt && !metrics.promptAt
        && !document.querySelector(".ant-welcome") && !document.querySelector(".chat-message-user")) metrics.emptyChatFrames++;
      if (metrics.promptAt && !window.chatPerformanceSource.finishedAt) {
        const prompts = document.querySelectorAll(".chat-message-user");
        if (!prompts.item(prompts.length - 1)?.textContent?.includes("Performance probe")) metrics.reorderedFrames++;
      }
      requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
    new PerformanceObserver(list => metrics.longTasks.push(...list.getEntries().map(entry => entry.duration))).observe({ type: "longtask", buffered: true });
    document.addEventListener("input", () => { const at = performance.now(); requestAnimationFrame(() => metrics.inputs.push({ at, delay: performance.now() - at })); }, true);
    document.addEventListener("DOMContentLoaded", () => {
      let previous = 0;
      let scheduled = false;
      new MutationObserver(() => {
        if (scheduled) return;
        scheduled = true;
        requestAnimationFrame(() => {
          scheduled = false;
          const prompts = document.querySelectorAll(".chat-message-user");
          if ([...prompts].some(item => item.textContent?.includes("Performance probe")) && !metrics.promptAt) metrics.promptAt = performance.now();
          const last = document.querySelectorAll(".chat-message-assistant");
          const content = last.item(last.length - 1)?.querySelector(".x-markdown")?.textContent ?? "";
          if (!metrics.formattedPreviewAt && content.includes("Incremental formatted reply")) metrics.formattedPreviewAt = performance.now();
          if (!content.startsWith("First reply.")) return;
          if (!metrics.firstReplyAt) metrics.firstReplyAt = performance.now();
          if (content.length !== previous) { previous = content.length; metrics.replyPaints.push({ at: performance.now(), length: content.length }); }
        });
      }).observe(document.documentElement, { childList: true, characterData: true, subtree: true });
    });
  });
});

test("first acceptance keeps the composer mounted and avoids an empty chat flash", async ({ page }, testInfo) => {
  await page.goto("https://chat.fixture/?new=true&firstSnapshotDelay=180&timelineDelay=600");
  const input = page.getByRole("textbox", { name: "Message", exact: true });
  await expect(input).toBeEnabled();
  await input.fill("Performance probe: first message.");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.locator(".chat-message-user")).toContainText("Performance probe: first message.");
  const result = await page.evaluate(() => ({ emptyChatFrames: window.chatPerformancePaint.emptyChatFrames,
    composerReplacements: window.chatPerformancePaint.composerReplacements }));
  console.log(JSON.stringify(result));
  await testInfo.attach("first-acceptance-paint", { body: JSON.stringify(result), contentType: "application/json" });
  expect(result.composerReplacements).toBe(0);
  expect(result.emptyChatFrames).toBe(0);
});

test("unfinished formatted text is readable while later chunks are still arriving", async ({ page }, testInfo) => {
  await page.goto("https://chat.fixture/?format=markdown&timelineDelay=600");
  const input = page.getByRole("textbox", { name: "Message", exact: true });
  await expect(input).toBeEnabled();
  await input.fill("Performance probe: formatted streaming.");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect.poll(() => page.evaluate(() => window.chatPerformanceSource.previewAt)).toBeGreaterThan(0);
  await expect(page.getByText(/Incremental formatted reply/)).toBeVisible({ timeout: 250 });
  await expect.poll(() => page.evaluate(() => window.chatPerformancePaint.formattedPreviewAt)).toBeGreaterThan(0);
  const delay = await page.evaluate(() => window.chatPerformancePaint.formattedPreviewAt - window.chatPerformanceSource.previewAt);
  expect(delay).toBeLessThan(250);
  expect(await page.evaluate(() => window.chatPerformanceSource.finishedAt)).toBe(0);
  await expect(page.getByRole("cell", { name: "Momentum", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: /^View research/ })).toHaveAttribute("href", "/research-runs/run_11111111111111111111");
  await expect.poll(() => page.evaluate(() => window.chatPerformanceSource.finishedAt)).toBeGreaterThan(0);
  const result = await page.evaluate(() => {
    const source = window.chatPerformanceSource;
    const paints = window.chatPerformancePaint.replyPaints.filter(paint => paint.at >= source.previewAt && paint.at <= source.formattedTextEndAt);
    return { previewDelayMs: window.chatPerformancePaint.formattedPreviewAt - source.previewAt,
      chunks: source.chunks, visibleReplyUpdates: window.chatPerformancePaint.replyPaints.length,
      longestFormattedTextGapMs: Math.max(0, ...paints.slice(1).map((paint, index) => paint.at - paints[index].at)) };
  });
  console.log(JSON.stringify(result));
  await testInfo.attach("formatted-preview", { body: JSON.stringify(result), contentType: "application/json" });
  expect(result.visibleReplyUpdates).toBeGreaterThan(25);
  expect(result.longestFormattedTextGapMs).toBeLessThan(250);
});

for (const withTool of [false, true]) test(`already readable words do not fade out or remount during formatted streaming (tool: ${withTool})`, async ({ page }, testInfo) => {
  await page.goto(`https://chat.fixture/?format=markdown&timelineDelay=600&tool=${withTool}`);
  const input = page.getByRole("textbox", { name: "Message", exact: true });
  await expect(input).toBeEnabled();
  const sampling = page.evaluate(async (withTool) => {
    const words = ["First", "Incremental", "longer", "explanation", "Momentum"];
    const visible = new Set<string>();
    const regressions: { word: string; opacity: number; at: number; text: string }[] = [];
    let firstReply: Element | null = null;
    let replyReplacements = 0;
    const vanishedWords: string[] = [];
    const promptPositions: number[] = [];
    const movement: object[] = [];
    let completedFrames = 0;
    while (completedFrames < 12) {
      await new Promise(requestAnimationFrame);
      if (window.chatPerformanceSource.finishedAt) completedFrames++;
      const reply = document.querySelector(".chat-message-assistant .x-markdown");
      if (!reply) continue;
      if (firstReply && firstReply !== reply) replyReplacements++;
      firstReply = reply;
      if (!withTool && window.chatPerformanceSource.chunks > 3) {
        const prompt = document.querySelector(".chat-message-user")!;
        const viewport = document.querySelector(".ant-bubble-list-scroll-box")!;
        if (reply.getBoundingClientRect().bottom - prompt.getBoundingClientRect().top < viewport.clientHeight - 50) {
          const y = prompt.getBoundingClientRect().top - viewport.getBoundingClientRect().top;
          if (!promptPositions.length || Math.abs(y - promptPositions.at(-1)!) > 1) movement.push({ y, chunk: window.chatPerformanceSource.chunks,
            replyHeight: reply.getBoundingClientRect().height, scrollTop: viewport.scrollTop, finished: !!window.chatPerformanceSource.finishedAt,
            margin: getComputedStyle(reply.closest(".ant-bubble")!).marginBlockEnd });
          promptPositions.push(y);
        }
      }
      const walker = document.createTreeWalker(reply, NodeFilter.SHOW_TEXT);
      const nodes: Node[] = [];
      while (walker.nextNode()) nodes.push(walker.currentNode);
      for (const word of words) {
        const node = nodes.find(node => node.textContent?.includes(word));
        if (!node) { if (visible.has(word)) vanishedWords.push(word); continue; }
        let opacity = 1;
        for (let element = node.parentElement; element; element = element.parentElement) {
          const style = getComputedStyle(element);
          opacity *= Number(style.opacity);
          if (style.visibility === "hidden" || style.display === "none") opacity = 0;
        }
        if (visible.has(word) && opacity < .95) regressions.push({ word, opacity, at: performance.now(), text: node.textContent!.slice(0, 80) });
        if (opacity >= .99) visible.add(word);
      }
    }
    return { wordsObserved: [...visible], regressions, replyReplacements, vanishedWords,
      promptTravel: Math.max(...promptPositions) - Math.min(...promptPositions), movement };
  }, withTool);
  await input.fill("Performance probe: stable streamed text.");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.locator(".chat-message-assistant")).toContainText("First reply.");
  expect(await page.evaluate(() => window.chatPerformanceSource.finishedAt)).toBe(0);
  const result = await sampling;
  await testInfo.attach("streaming-word-visibility", { body: JSON.stringify(result, null, 2), contentType: "application/json" });
  expect(result.wordsObserved).toEqual(expect.arrayContaining(["First", "Incremental", "Momentum"]));
  expect(result.regressions, "Previously readable words must stay opaque as more Markdown arrives").toEqual([]);
  expect(result.replyReplacements).toBe(0);
  expect(result.vanishedWords).toEqual([]);
  if (!withTool) expect(result.promptTravel, "The anchored prompt must not bounce while the reply fits the viewport").toBeLessThanOrEqual(1);
});
for (const { history, cards } of [{ history: 0, cards: 0 }, { history: 20, cards: 0 }, { history: 20, cards: 5 }]) test(`input and streamed replies stay responsive with ${history} earlier turns and ${cards} research cards`, async ({ page }, testInfo) => {
  await page.goto(`https://chat.fixture/?history=${history}&cards=${cards}&timelineDelay=600`);
  const input = page.getByRole("textbox", { name: "Message", exact: true });
  await expect(input).toBeEnabled();
  if (cards) await expect(page.getByRole("region", { name: /^ResearchRun / })).toHaveCount(cards);
  await page.evaluate(() => { window.chatPerformancePaint.inputs.length = 0; window.chatPerformancePaint.frames.length = 0; window.chatPerformancePaint.longTasks.length = 0; });
  await input.pressSequentially("Performance probe: show a streamed answer.", { delay: 12 });
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.getByText(/^First reply/)).toBeVisible();
  await input.pressSequentially("A follow-up draft typed while streaming.", { delay: 12 });
  await expect(page.getByText(/First reply.*Part 49/)).toBeVisible({ timeout: 15_000 });
  await expect(input).toHaveValue("A follow-up draft typed while streaming.");
  await expect.poll(() => page.evaluate(() => window.chatPerformanceSource.finishedAt)).toBeGreaterThan(0);
  const result = await page.evaluate(() => {
    const source = window.chatPerformanceSource;
    const paint = window.chatPerformancePaint;
    const percentile = (values: number[], fraction: number) => [...values].sort((a, b) => a - b)[Math.floor((values.length - 1) * fraction)] ?? 0;
    return { history: document.querySelectorAll(".chat-message-user").length - 1, promptAfterAcceptanceMs: paint.promptAt - source.acceptedAt,
      firstChunkToPaintMs: paint.firstReplyAt - source.firstChunkAt,
      inputP95Ms: percentile(paint.inputs.filter(item => item.at < source.acceptedAt).map(item => item.delay), .95),
      streamingInputP95Ms: percentile(paint.inputs.filter(item => item.at >= source.acceptedAt && item.at <= source.finishedAt).map(item => item.delay), .95),
      frameP95Ms: percentile(paint.frames, .95), reorderedFrames: paint.reorderedFrames,
      longestTaskMs: Math.max(0, ...paint.longTasks), timelineRequests: source.timelineRequests, chunks: source.chunks,
      visibleReplyUpdates: paint.replyPaints.length, replyGapsMs: paint.replyPaints.slice(1).map((item: {at: number}, index: number) => item.at - paint.replyPaints[index].at) };
  });
  console.log(JSON.stringify(result));
  await testInfo.attach("chat-performance", { body: JSON.stringify(result, null, 2), contentType: "application/json" });
  expect(result.promptAfterAcceptanceMs).toBeLessThan(250);
  expect(result.firstChunkToPaintMs).toBeLessThan(250);
  expect(result.inputP95Ms).toBeLessThan(100);
  expect(result.streamingInputP95Ms).toBeLessThan(100);
  expect(result.visibleReplyUpdates).toBeGreaterThan(15);
  expect(result.frameP95Ms).toBeLessThan(50);
  expect(result.reorderedFrames, "An older HTTP snapshot must not move the active turn before history").toBe(0);
});
