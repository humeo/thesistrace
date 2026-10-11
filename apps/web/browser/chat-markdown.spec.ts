import { expect, test } from "@playwright/test";
import { buildModuleProductFixture } from "./build-product-fixture";

let files: Awaited<ReturnType<typeof buildModuleProductFixture>>;
test.use({ viewport: { width: 1159, height: 964 }, permissions: ["clipboard-read", "clipboard-write"] });
test.beforeAll(async () => {
  test.setTimeout(60_000);
  files = await buildModuleProductFixture(new URL("./fixtures/chat-markdown.tsx", import.meta.url));
});
test.beforeEach(async ({ page }) => {
  await page.route("https://markdown.fixture/**", route => {
    const path = new URL(route.request().url()).pathname.slice(1) || "index.html";
    const asset = files.get(path);
    return asset ? route.fulfill(asset) : route.fulfill({ status: 404, body: "" });
  });
});

for (const streaming of [false, true]) {
  test(`Python blocks are highlighted and copy original source (streaming=${streaming})`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    page.on("console", message => { if (message.type() === "warning" || message.type() === "error") errors.push(message.text()); });
    await page.goto(`https://markdown.fixture/?streaming=${streaming}`);
    const block = page.locator(".ant-codeHighlighter");
    await expect(block.getByText("python", { exact: true })).toBeVisible();
    const code = block.locator("pre > code");
    const source = "from quantgrove import Targets\n\n\ndef compute(data, state):\n    return Targets.equal_weight(\n        data.eligible,\n        update=(data.session_index % 5 == 0) & data.eligible.any(axis=0),\n        reason='Equal-weight eligible universe; rebalance every 5 sessions',\n    )\n";
    const keyword = code.getByText("from", { exact: true });
    await expect(keyword).toBeVisible();
    if (streaming) {
      expect(await code.textContent()).toBe(source.slice(0, source.indexOf("        update=")).trimEnd());
      await page.getByRole("button", { name: "Complete stream" }).click();
    }
    expect(await keyword.evaluate(element => getComputedStyle(element).color))
      .not.toBe(await code.evaluate(element => getComputedStyle(element).color));
    expect(await code.textContent()).toBe(source.trimEnd());
    await block.getByRole("button").click();
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(source);
    await expect(code).toHaveCSS("white-space", "pre");
    await expect(code).toHaveCSS("line-height", "24px");
    const prose = page.locator(".chat-markdown-reading");
    await expect(prose.locator("p")).toHaveCSS("line-height", "26px");
    await expect(prose.locator("strong")).toHaveCSS("font-weight", "600");
    const inline = prose.locator("p code");
    await expect(inline).toHaveText("data.eligible");
    await expect(inline).toHaveCSS("padding", "2px 6px");
    await expect(inline).toHaveCSS("line-height", "20px");
    await expect(prose.getByRole("table")).toHaveCSS("font-size", "14px");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(errors).toEqual([]);
  });
}

for (const language of ["", "quantgrove-formula"]) {
  test(`code without a recognized grammar remains readable and copyable (${language || "unlabelled"})`, async ({ page }) => {
    await page.goto(`https://markdown.fixture/?language=${language}`);
    const block = page.locator(".ant-codeHighlighter");
    await expect(block.getByText(language || "text", { exact: true })).toBeVisible();
    const source = "x < y && y > z\n    **keep literal**\n\ttab-indented\nlong line: " + "x".repeat(160) + "\n";
    await expect.poll(() => block.locator("pre code").textContent()).toBe(source.trimEnd());
    await block.getByRole("button").focus();
    await page.keyboard.press("Enter");
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(source);
    expect(await block.locator("pre").evaluate(element => element.scrollWidth > element.clientWidth)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
