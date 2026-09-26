import { expect, test } from "@playwright/test";
import { buildProductFixture } from "./build-product-fixture";

let styles: string;
let timelineScript: string;

test.beforeAll(async () => {
  ({ script: timelineScript, styles } = await buildProductFixture(new URL("./fixtures/chat-timeline.tsx", import.meta.url), "ChatTimelineFixture"));
});

test.beforeEach(async ({ page }) => {
  await page.setContent(`<style>${styles}</style><div id="root"></div>`);
  await page.addScriptTag({ content: timelineScript });
});


test("completion keeps compact results and treats answers as tool history", async ({ page }) => {
  await expect(page.locator('[data-entry-id="progress"]')).toBeVisible();
  await page.getByRole("button", { name: "Complete", exact: true }).click();
  await expect(page.locator('[data-entry-id="progress"]')).toBeHidden();
  await expect(page.locator('[data-entry-id="result"]')).toBeVisible();
  await expect(page.locator('[data-entry-id="other-result"]')).toBeVisible();
  await expect(page.locator('[data-entry-id="final"]')).toBeVisible();
  const footer = page.locator('.chat-response-footer');
  await page.mouse.move(0, 0);
  await expect(footer).toHaveCSS('opacity', '0');
  await page.locator('.chat-turn-response').hover();
  await expect(footer).toHaveCSS('opacity', '1');
  await expect(footer.locator('time')).toHaveAttribute('datetime', '2026-09-06T00:00:00.000Z');
  const footerBox = (await footer.boundingBox())!;
  const finalBox = (await page.locator('[data-entry-id="final"]').boundingBox())!;
  const contentBox = (await page.locator('.chat-timeline-content').boundingBox())!;
  expect(footerBox.y).toBeGreaterThanOrEqual(finalBox.y + finalBox.height);
  expect(footerBox.y - finalBox.y - finalBox.height).toBeLessThanOrEqual(12);
  expect(contentBox.y + contentBox.height - footerBox.y - footerBox.height).toBeGreaterThanOrEqual(56);
  expect(contentBox.y + contentBox.height - finalBox.y - finalBox.height).toBeLessThanOrEqual(112);
  expect(footerBox.x).toBe(finalBox.x);
  await page.mouse.move(0, 0);
  await footer.getByRole('button', { name: 'Copy response' }).focus();
  await expect(footer).toHaveCSS('opacity', '1');
  await expect(page.locator('[data-entry-id="before"]')).toBeHidden();
  await expect(page.locator('[data-entry-id="between"]')).toBeHidden();
  await page.locator('.chat-work-history > [data-slot="collapsible-trigger"]').click();
  await expect(page.locator('[data-entry-id="before"]')).toBeVisible();
  await expect(page.locator('[data-entry-id="between"]')).toBeVisible();
  await expect(page.getByText('Last observed progress', { exact: true })).toHaveCount(0);
  await expect(page.locator('.chat-message-user')).toHaveCount(0);
  await page.locator('.chat-tool-group > [data-slot="collapsible-trigger"]').last().click();
  const question = page.locator('[data-tool-name="ask_user"]');
  await expect(question).toBeVisible();
  await question.getByText('Question and answer', { exact: true }).click();
  await expect(question.getByText('Default approach', { exact: true })).toBeVisible();
  expect(await page.locator('.chat-message-assistant').allTextContents()).toEqual([
    "Checking the research context.", "The context is ready. Checking the results.", "Both research tasks finished.",
  ]);
  await page.getByRole("button", { name: "Fail", exact: true }).click();
  await expect(page.getByText("Last observed progress", { exact: true })).toHaveCount(0);
});

test("new turns start near the top and keep their position through a short reply", async ({ page }) => {
  await page.getByRole("button", { name: "Complete", exact: true }).click();
  await page.getByRole("button", { name: "Send next", exact: true }).click();
  const viewport = page.getByRole("log");
  const latest = page.locator('.chat-turn').last();
  const offset = async () => (await latest.boundingBox())!.y - (await viewport.boundingBox())!.y;
  await expect.poll(offset).toBeGreaterThanOrEqual(88);
  await expect.poll(offset).toBeLessThanOrEqual(104);
  await expect.poll(offset).toBeCloseTo(96, 0);
  const initialOffset = await offset();
  await page.getByRole("button", { name: "Short reply", exact: true }).click();
  await expect.poll(offset).toBeCloseTo(initialOffset, 0);
  await page.getByRole("button", { name: "Finish reply", exact: true }).click();
  await expect.poll(offset).toBeCloseTo(initialOffset, 0);
  const bubble = (await latest.locator('.chat-message-user').boundingBox())!;
  const work = (await latest.locator('.chat-turn-assistant-meta').boundingBox())!;
  const previousFooter = (await page.locator('.chat-turn').first().locator('.chat-response-footer').boundingBox())!;
  expect(work.y - bubble.y - bubble.height).toBeGreaterThanOrEqual(0);
  expect(work.y - bubble.y - bubble.height).toBeLessThanOrEqual(24);
  expect(bubble.y - previousFooter.y - previousFooter.height).toBeGreaterThanOrEqual(0);
  expect(bubble.y - previousFooter.y - previousFooter.height).toBeLessThanOrEqual(24);
  await latest.locator('.chat-message-user').hover();
  await expect(latest.locator('.chat-message-actions')).toHaveCSS('opacity', '1');
  const userCopy = (await latest.getByRole('button', { name: 'Copy your message' }).boundingBox())!;
  const reply = (await latest.locator('.chat-message-assistant').boundingBox())!;
  expect(userCopy.y + userCopy.height).toBeLessThanOrEqual(reply.y);
  await viewport.hover();
  await page.mouse.wheel(0, -180);
  await expect.poll(() => viewport.evaluate((el) => el.scrollHeight - el.clientHeight - el.scrollTop)).toBeGreaterThan(100);
  await expect(latest.locator('.chat-message-assistant')).toBeInViewport({ ratio: 1 });
  await expect(page.getByRole("button", { name: "Back to latest" })).toBeHidden();
  await page.mouse.wheel(0, 500);
  await expect.poll(() => viewport.evaluate((el) => el.scrollHeight - el.clientHeight - el.scrollTop)).toBeLessThanOrEqual(2);
  await page.setViewportSize({ width: 390, height: 700 });
  await expect.poll(offset).toBeGreaterThanOrEqual(88);
  await expect.poll(offset).toBeLessThanOrEqual(104);
  await page.getByRole("button", { name: "Long reply", exact: true }).click();
  await expect.poll(() => viewport.evaluate((el) => el.scrollHeight - el.clientHeight - el.scrollTop)).toBeLessThanOrEqual(2);
  await viewport.hover();
  await page.mouse.wheel(0, -300);
  await expect(page.getByRole("button", { name: "Back to latest" })).toBeVisible();
  const readingPosition = await viewport.evaluate((el) => el.scrollTop);
  await page.getByRole("button", { name: "Long reply", exact: true }).click();
  await expect.poll(() => viewport.evaluate((el) => el.scrollTop)).toBeCloseTo(readingPosition, 0);
  await page.getByRole("button", { name: "Send next", exact: true }).click();
  await expect.poll(offset).toBeGreaterThanOrEqual(88);
  await expect.poll(offset).toBeLessThanOrEqual(104);
});

for (const reducedMotion of ["no-preference", "reduce"] as const) {
  test(`sending moves smoothly above the reply area with motion preference ${reducedMotion}`, async ({ page }) => {
    await page.emulateMedia({ reducedMotion });
    await page.getByRole("button", { name: "Complete", exact: true }).click();
    const positions = await page.evaluate(async () => {
      const viewport = document.querySelector('.chat-timeline')!;
      const send = [...document.querySelectorAll('button')].find((button) => button.textContent === 'Send next')!;
      send.click();
      return new Promise<number[]>((resolve) => {
        const samples: number[] = [];
        const start = performance.now();
        function sample() {
          const latest = document.querySelector('[data-turn-id="sent-1"]');
          if (!latest) { requestAnimationFrame(sample); return; }
          const offset = latest.getBoundingClientRect().top - viewport.getBoundingClientRect().top;
          samples.push(offset);
          if (samples.length === 1) {
            [...document.querySelectorAll('button')].find((button) => button.textContent === 'Short reply')!.click();
          }
          if (Math.abs(offset - 96) < 0.5 || performance.now() - start > 1500) resolve(samples);
          else requestAnimationFrame(sample);
        }
        requestAnimationFrame(sample);
      });
    });
    expect(positions.at(-1)).toBeCloseTo(96, 0);
    if (reducedMotion === 'reduce') expect(positions).toEqual([expect.closeTo(96, 0)]);
    else expect(new Set(positions.filter((value) => value > 104).map(Math.round)).size).toBeGreaterThan(2);
  });
}

test("latest tool status stays visible when history is folded and respects reduced motion", async ({ page }) => {
  await page.getByRole("button", { name: "Start tool", exact: true }).click();
  const activity = page.locator(".chat-current-activity");
  await expect(activity).toContainText("Running submit research run");
  await page.locator('.chat-work-history > [data-slot="collapsible-trigger"]').click();
  await expect(activity).toBeVisible();
  await expect(page.locator('.chat-work-history > [data-slot="collapsible-trigger"]')).toContainText("Working for");
  await expect(activity).toHaveAttribute("role", "status");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(activity.locator("span")).toHaveCSS("animation-name", "none");
  await expect(activity).toBeVisible();
  await page.getByRole("button", { name: "Finish tool", exact: true }).click();
  await expect(activity).toContainText("Preparing response");
  await page.getByRole("button", { name: "Complete", exact: true }).click();
  await expect(activity).toHaveCount(0);
  await expect(page.locator('.chat-work-history > [data-slot="collapsible-trigger"]')).toContainText("Worked for");
});

test("renders Chinese punctuation emphasis while preserving code in a completed reply", async ({ page }) => {
  await page.getByRole("button", { name: "Send next", exact: true }).click();
  await page.getByRole("button", { name: "CJK reply", exact: true }).click();
  const message = page.locator('[data-entry-id="sent-1-response"]');
  await expect(message.locator("strong")).toHaveText("数据截至：");
  await expect(message.locator("code")).toHaveText("**原文：**保持");
  await expect(message).toContainText("2026-08-27");
});

test("short Markdown run links remain reachable on a phone", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Send next", exact: true }).click();
  await page.getByRole("button", { name: "Run link reply", exact: true }).click();
  const link = page.getByRole("link", { name: "X", exact: true });
  await expect(link).toHaveAttribute("href", "/research-runs/run_0123456789abcdef0123");
  const bounds = (await link.boundingBox())!;
  expect(bounds.width).toBeGreaterThanOrEqual(44);
  expect(bounds.height).toBeGreaterThanOrEqual(44);
});
for (const failed of [false, true]) {
  test(`copy feedback is visible when clipboard ${failed ? "rejects" : "succeeds"}`, async ({ page }) => {
    await page.evaluate(failed => Object.defineProperty(navigator, "clipboard", { configurable: true, value: {
      writeText: async () => { if (failed) throw new DOMException("Denied", "NotAllowedError"); },
    } }), failed);
    await page.getByRole("button", { name: "Complete", exact: true }).click();
    await page.locator(".chat-turn-response").hover();
    await page.getByRole("button", { name: "Copy response", exact: true }).click();
    await expect(page.locator("[data-slot=toast]")).toContainText(failed ? "Could not copy to clipboard." : "Copied to clipboard.");
    await expect(page.locator("[data-slot=toast]")).toBeVisible();
    await expect(page.locator('[data-entry-id="final"]')).toBeVisible();
  });
}
