import { expect, test } from "@playwright/test";
import { serveBrandAssets } from "./brand-assets";
import { buildModuleProductFixture } from "./build-product-fixture";
let files: Awaited<ReturnType<typeof buildModuleProductFixture>>;
test.use({ viewport: { width: 1159, height: 964 } });
test.beforeAll(async () => {
  test.setTimeout(60_000);
  files = await buildModuleProductFixture(new URL("./fixtures/chat-composer.tsx", import.meta.url));
});
test.beforeEach(async ({ page }) => {
  await page.route("https://chat.fixture/**", route => {
    const path = new URL(route.request().url()).pathname.slice(1) || "index.html";
    const asset = files.get(path);
    return asset ? route.fulfill(asset) : route.fulfill({ status: 404, body: "" });
  });
  await serveBrandAssets(page);
  await page.goto("https://chat.fixture/");
});
test("new chat starter cards fill an editable draft without sending it", async ({ page }) => {
  const examples = [
    { label: "评估因子", prompt: "帮我评估 20 日动量因子 rank(pct_change(close, 20))，分析它的预测能力与稳定性。" },
    { label: "回测策略", prompt: "帮我回测一个每月调仓的低估值策略，并分析收益、回撤和换手率。" },
    { label: "比较结果", prompt: "帮我列出已有的研究结果，选择可比的结果，对比收益、回撤和风险指标。" },
    { label: "跟踪策略", prompt: "帮我查看正在跟踪的策略，汇总最新表现、持仓变化和风险情况。" },
  ];
  await page.getByRole("button", { name: "简体中文", exact: true }).click();
  const cards = page.getByRole("region", { name: "研究问题示例", exact: true });
  await expect(cards.getByRole("button")).toHaveCount(4);
  const input = page.getByRole("textbox", { name: "消息", exact: true });
  for (const { label, prompt } of examples) {
    await cards.getByRole("button", { name: label, exact: true }).click();
    await expect(input).toHaveValue(prompt);
    await expect(input).toBeFocused();
    await expect(page.locator("[data-answer-receipt]")).toHaveText("");
  }
  await input.fill("我的自定义研究问题");
  await page.getByRole("button", { name: "English", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Message", exact: true })).toHaveValue("我的自定义研究问题");
  const factorCard = page.getByRole("button", { name: "Evaluate factors", exact: true });
  await factorCard.focus();
  await factorCard.press("Enter");
  await expect(page.getByRole("textbox", { name: "Message", exact: true })).toHaveValue("Evaluate the 20-day momentum factor rank(pct_change(close, 20)) and analyze its predictive power and stability.");
  await expect(page.getByRole("textbox", { name: "Message", exact: true })).toBeFocused();
  await expect(page.locator("[data-answer-receipt]")).toHaveText("");
});
test("new chat centers the welcome, composer and starter cards together on desktop", async ({ page }) => {
  for (const language of ["English", "简体中文"]) {
    await page.getByRole("button", { name: language, exact: true }).click();
    await expect(page.locator(".ant-welcome-icon")).toHaveText("Quantgrove");
    await expect(page.locator(".ant-welcome-title")).toHaveText(language === "简体中文" ? "从一个研究问题开始" : "Start with a research question");
    await expect(page.locator(".ant-welcome-description")).toHaveCount(0);
    const cards = page.getByRole("region", { name: language === "简体中文" ? "研究问题示例" : "Research question examples", exact: true });
    await expect(cards.getByRole("button")).toHaveCount(4);
    await expect(page.getByRole("textbox", { name: language === "简体中文" ? "消息" : "Message", exact: true })).toHaveAttribute("placeholder", language === "简体中文"
      ? "例如：回测一个每月调仓的低估值策略..." : "For example: backtest a value strategy with monthly rebalancing…");
    const main = (await page.locator("main.quantgrove-chat").boundingBox())!;
    const welcome = (await page.locator(".ant-welcome").boundingBox())!;
    const sender = (await page.locator(".ant-sender").boundingBox())!;
    const cardsBox = (await cards.boundingBox())!;
    expect(sender.y - welcome.y - welcome.height).toBe(40);
    expect(cardsBox.y - sender.y - sender.height).toBe(40);
    expect(sender.width - cardsBox.width).toBe(48);
    expect(Math.abs(cardsBox.x + cardsBox.width / 2 - main.x - main.width / 2)).toBeLessThanOrEqual(1);
    expect(Math.abs(welcome.x + welcome.width / 2 - main.x - main.width / 2)).toBeLessThanOrEqual(1);
    expect(Math.abs((welcome.y + cardsBox.y + cardsBox.height) / 2 - main.y - main.height / 2)).toBeLessThanOrEqual(1);
    expect(Math.abs(sender.x + sender.width / 2 - main.x - main.width / 2)).toBeLessThanOrEqual(1);
    const cardBoxes = await Promise.all((await cards.getByRole("button").all()).map(card => card.boundingBox()));
    expect(cardBoxes.every(box => Math.abs(box!.y - cardBoxes[0]!.y) <= 1 && Math.abs(box!.width - cardBoxes[0]!.width) <= 1)).toBe(true);
    const outerBoxes = await Promise.all((await cards.locator(".ant-prompts-item").all()).map(card => card.boundingBox()));
    for (let index = 1; index < outerBoxes.length; index++) {
      expect(outerBoxes[index]!.x - outerBoxes[index - 1]!.x - outerBoxes[index - 1]!.width).toBe(16);
    }
    for (const card of await cards.locator(".ant-prompts-item").all()) {
      const outer = (await card.boundingBox())!;
      const button = (await card.getByRole("button").boundingBox())!;
      expect(button.y - outer.y).toBe(1);
      expect(outer.y + outer.height - button.y - button.height).toBe(1);
      expect(outer.width - button.width).toBe(2);
    }
    expect(await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
});
test("language switch preserves an unsent prompt and a pending-question answer on desktop", async ({ page }) => {
  await page.setViewportSize({ width: 1159, height: 780 });
  const prompt = page.getByRole("textbox", { name: "Message" });
  await prompt.fill("My own signal stays unchanged");
  await prompt.focus();
  await page.getByRole("button", { name: "简体中文", exact: true }).evaluate(element => (element as HTMLButtonElement).click());
  await expect(page.getByRole("textbox", { name: "消息" })).toHaveValue("My own signal stays unchanged");
  await expect(page.getByRole("textbox", { name: "消息" })).toBeFocused();
  await expect(page.getByRole("button", { name: "发送", exact: true })).toBeEnabled();
  await page.getByLabel("Test question mode").selectOption("multi_select");
  await page.getByText("Quality", { exact: true }).click();
  await page.getByRole("textbox", { name: "回答" }).fill("Keep the authored answer");
  const choices = page.getByRole("checkbox", { name: "Quality" });
  await expect(choices).toBeChecked();
  await page.getByRole("button", { name: "English", exact: true }).evaluate(element => (element as HTMLButtonElement).click());
  await expect(page.getByRole("textbox", { name: "Answer" })).toHaveValue("Keep the authored answer");
  await expect(choices).toBeChecked();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

for (const mobile of [false]) {
  test(`question composer supports options plus text, custom-only and Stop on ${mobile ? "mobile" : "desktop"}`, async ({ page }) => {
    await page.setViewportSize(mobile ? { width: 390, height: 844 } : { width: 1159, height: 964 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    const mode = page.getByLabel("Test question mode");
    await mode.selectOption("single_select");
    const answer = page.getByRole("textbox", { name: "Answer", exact: true });
    const send = page.getByRole("button", { name: "Send answer", exact: true });
    await expect(answer).toBeEnabled();
    await expect(answer).toHaveAccessibleDescription(/Enter to answer.*Shift\+Enter for newline/);
    await expect(page.locator(".chat-composer-guidance")).toHaveCount(0);
    await expect(send).toBeDisabled();
    await answer.press("Enter");
    await expect(page.locator(".chat-question-composer")).toBeVisible();
    await page.getByText("Quality", { exact: true }).click();
    await expect(page.getByRole("radio", { name: "Quality", exact: true })).toBeChecked();
    await answer.fill("Keep turnover low.");
    await expect(answer).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
    await expect(answer).toHaveCSS("outline-style", "none");
    await expect(page.getByRole("button", { name: /^Model / })).toHaveCount(0);
    expect((await send.boundingBox())!.height).toBeGreaterThanOrEqual(24);
    await answer.press("Tab");
    await expect(send).toBeFocused();
    await expect(send).not.toHaveCSS("outline-style", "none");
    await send.press("Enter");
    await expect(page.locator("[data-answer-receipt]")).toHaveText("Quality\n\nKeep turnover low.");

    await mode.selectOption("multi_select");
    await page.getByText("Quality", { exact: true }).click();
    await page.getByText("Risk", { exact: true }).click();
    await page.getByRole("button", { name: "Clear", exact: true }).click();
    await expect(send).toBeDisabled();
    await answer.fill("Research liquidity instead.");
    await answer.press("Enter");
    await expect(page.locator("[data-answer-receipt]")).toHaveText("Research liquidity instead.");

    await mode.selectOption("free_text");
    await answer.fill("A custom answer");
    await page.getByRole("button", { name: "Stop", exact: true }).click();
    await expect(page.locator("[data-answer-receipt]")).toHaveText("Stopped");
    await expect(page.locator(".chat-question-composer")).toHaveCount(0);
  });

  test(`long question composer keeps its answer row reachable on ${mobile ? "mobile" : "desktop"}`, async ({ page }) => {
    await page.setViewportSize(mobile ? { width: 390, height: 844 } : { width: 1159, height: 964 });
    await page.getByLabel("Test question mode").selectOption("long");
    const panel = page.locator(".chat-question-composer");
    const body = page.locator(".chat-question-body");
    const answer = page.getByRole("textbox", { name: "Answer", exact: true });
    await expect(panel).toBeVisible();
    await expect(body).toHaveCSS("overflow-y", "auto");
    expect(await body.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(true);
    await page.getByText("Objective 20", { exact: true }).click();
    await expect(page.getByRole("checkbox", { name: "Objective 20", exact: true })).toBeChecked();
    await answer.fill("A note\n".repeat(30));
    await expect(page.getByRole("button", { name: "Send answer", exact: true })).toBeInViewport();
    const panelBox = (await panel.boundingBox())!;
    const rowBox = (await page.locator(".chat-question-answer-row").boundingBox())!;
    const answerBox = (await answer.boundingBox())!;
    await test.info().attach("question-layout", {
      body: JSON.stringify({ panelBox, rowBox, answerBox, geometry: await panel.evaluate((element) =>
        [element, ...element.children].map((node) => ({
          className: node.className,
          scrollTop: node.scrollTop,
          scrollHeight: node.scrollHeight,
          clientHeight: node.clientHeight,
          height: getComputedStyle(node).height,
          flex: getComputedStyle(node).flex,
        }))) }),
      contentType: "application/json",
    });
    expect(rowBox.height).toBeLessThanOrEqual(answerBox.height + 64);
    expect(panelBox.y + panelBox.height - rowBox.y - rowBox.height).toBeLessThanOrEqual(12);
    expect(await panel.evaluate((element) => element.scrollTop)).toBe(0);
    expect(answerBox.height).toBeLessThanOrEqual(140);
    expect((await panel.boundingBox())!.height).toBeLessThanOrEqual(mobile ? 549 : 560);
    expect(await page.locator("body").evaluate((element) => element.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: `${test.info().outputDir}/question-${mobile ? "mobile" : "desktop"}.png` });
  });

}
for (const width of [1280]) {
  test(`model settings preserve draft and keyboard focus at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const input = page.getByRole("textbox", { name: "Message", exact: true });
    await input.fill("Keep my research draft");
    const trigger = page.getByRole("button", { name: /^Model / });
    await trigger.focus();
    await trigger.press("ArrowDown");
    const popup = page.getByRole("dialog");
    const luna = popup.getByRole("radio", { name: "GPT-5.6 Luna", exact: true });
    await expect(luna).toBeFocused();
    await expect(popup.getByRole("slider", { name: "Reasoning", exact: true })).toHaveAttribute("aria-valuemax", "4");
    await luna.press("ArrowDown");
    const sol = popup.getByRole("radio", { name: "GPT-5.6 Sol", exact: true });
    await expect(sol).toBeFocused();
    await expect(sol).toBeChecked();
    await expect(popup).toBeVisible();
    await sol.press("Tab");
    const reasoning = popup.getByRole("slider", { name: "Reasoning", exact: true });
    await expect(reasoning).toBeFocused();
    expect(await reasoning.evaluate(el => getComputedStyle(el, "::after").outlineStyle)).not.toBe("none");
    await expect(reasoning).toHaveAttribute("aria-valuemax", "3");
    await expect(reasoning).toHaveAttribute("aria-valuetext", "X-high");
    await reasoning.press("ArrowLeft");
    await expect(reasoning).toHaveAttribute("aria-valuetext", "High");
    await reasoning.press("ArrowLeft");
    await expect(reasoning).toHaveAttribute("aria-valuetext", "Medium");
    await expect(popup).toBeVisible();
    await reasoning.press("Escape");
    await expect(popup).toBeHidden();
    await expect(trigger).toBeFocused();
    await expect(popup).toHaveCount(0);
    await trigger.click();
    await page.getByRole("button", { name: "简体中文", exact: true }).click();
    // The language control is outside this non-modal popover and dismisses it.
    await expect(popup).toHaveCount(0);
    await page.locator('button[aria-haspopup="dialog"]').click();
    const localizedReasoning = popup.getByRole("slider", { name: "推理强度", exact: true });
    await expect(localizedReasoning).toHaveAttribute("aria-valuetext", "中");
    const track = popup.locator('.ant-slider-rail');
    const trackBox = (await track.boundingBox())!;
    await popup.locator('.ant-slider-mark').getByText("很高", { exact: true }).click();
    await expect(localizedReasoning).toHaveAttribute("aria-valuetext", "很高");
    await expect(popup).toBeVisible();
    await localizedReasoning.hover();
    const thumbBox = (await localizedReasoning.boundingBox())!;
    await page.mouse.move(thumbBox.x + thumbBox.width / 2, thumbBox.y + thumbBox.height / 2);
    await page.mouse.down();
    await page.mouse.move(trackBox.x + 4, trackBox.y + trackBox.height / 2, { steps: 8 });
    await page.mouse.up();
    await expect(localizedReasoning).toHaveAttribute("aria-valuetext", "低");
    await localizedReasoning.press("Escape");
    await expect(popup).toBeHidden();
    await expect(page.getByRole("textbox", { name: "消息", exact: true })).toHaveValue("Keep my research draft");
    await expect(page.locator('button[aria-haspopup="dialog"]')).toBeFocused();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}

for (const mode of ["single_select", "multi_select"]) {
  test(`question ${mode} shows keyboard focus on the option`, async ({ page }) => {
    await page.getByLabel("Test question mode").selectOption(mode);
    const option = page.getByRole(mode === "single_select" ? "radio" : "checkbox", { name: "Quality", exact: true });
    await page.keyboard.press("Tab");
    await option.focus();
    await expect(option).toBeFocused();
    await expect(option.locator("xpath=..")).not.toHaveCSS("outline-style", "none");
    await option.press("Space");
    await expect(option).toBeChecked();
    await expect(option.locator("xpath=..")).not.toHaveCSS("outline-style", "none");
  });
}

test("native composer sends with Enter, grows for multiline text and preserves rejected drafts", async ({ page }) => {
  const input = page.getByRole("textbox", { name: "Message", exact: true });
  const send = page.getByRole("button", { name: "Send", exact: true });
  await expect(send).toBeDisabled();
  await expect(input).toHaveAccessibleDescription(/Enter to send.*Shift\+Enter for newline/);
  await input.fill("Investigate quality.");
  await input.press("Shift+Enter");
  await input.pressSequentially("Keep turnover low.");
  await expect(input).toHaveValue("Investigate quality.\nKeep turnover low.");
  await input.press("Enter");
  await expect(page.locator("[data-answer-receipt]")).toHaveText("Investigate quality.\nKeep turnover low.");
  await expect(input).toHaveValue("");
  const emptyHeight = (await input.boundingBox())!.height;
  await input.fill("A multiline research draft.\n".repeat(30));
  await expect.poll(async () => (await input.boundingBox())!.height).toBeGreaterThan(emptyHeight);
  expect(await input.evaluate(element => element.scrollHeight > element.clientHeight)).toBe(true);
  await input.fill("Short draft");
  await expect.poll(async () => (await input.boundingBox())!.height).toBeLessThanOrEqual(emptyHeight + 1);
  await page.getByLabel("Test question mode").selectOption("rejected");
  await input.fill("Retain this prompt");
  await input.press("Enter");
  await expect(page.getByRole("alert")).toContainText("Prompt rejected");
  await expect(input).toHaveValue("Retain this prompt");
  await send.click();
  await expect(input).toHaveValue("Retain this prompt");
});

test("native staged queue preserves full text, FIFO actions and draft locking", async ({ page }) => {
  await page.getByLabel("Test question mode").selectOption("queue");
  const queue = page.locator(".chat-staged-queue");
  const first = queue.locator('[data-staged-input="fixture-0"]');
  await first.getByRole("button", { name: /First staged prompt.*With context/ }).click();
  await expect(first.getByText("First staged prompt\nWith context", { exact: true }).last()).toBeVisible();
  await expect(first.getByText("First staged prompt\nWith context", { exact: true }).last()).toHaveCSS("white-space", "pre-wrap");
  await expect(queue.getByRole("button", { name: "Steer", exact: true })).toHaveCount(1);
  const draft = page.getByRole("textbox", { name: "Message", exact: true });
  await draft.fill("Protect the existing draft");
  for (const edit of await queue.getByRole("button", { name: "Edit staged input", exact: true }).all()) {
    await expect(edit).toBeDisabled();
  }
  await draft.fill("");
  await first.getByRole("button", { name: "Steer", exact: true }).click();
  await expect(page.locator("[data-answer-receipt]")).toHaveText("Steered: First staged prompt\nWith context");
  const second = queue.locator('[data-staged-input="fixture-1"]');
  await second.getByRole("button", { name: "Steer", exact: true }).press("Tab");
  const edit = second.getByRole("button", { name: "Edit staged input", exact: true });
  await expect(edit).toBeFocused();
  await edit.press("Enter");
  await expect(draft).toHaveValue("Second staged prompt");
  await expect(queue).toHaveCount(0);
  await page.getByLabel("Test question mode").selectOption("normal");
  await page.getByLabel("Test question mode").selectOption("queue");
  await queue.locator('[data-staged-input="fixture-1"]').getByRole("button", { name: "Delete staged input", exact: true }).click();
  await expect(queue.locator("[data-staged-input]")).toHaveCount(1);
});
