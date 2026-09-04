import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { build } from "vite";

const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
let composerScript: string;

test.beforeAll(async () => {
  // Bundle the actual component, not a copy of its markup or resizing logic.
  // This browser test needs no server, Auth, Agent, or database.
  const result = await build({
    configFile: false,
    logLevel: "silent",
    esbuild: { jsx: "automatic" },
    define: { "process.env.NODE_ENV": JSON.stringify("production") },
    build: {
      write: false,
      minify: false,
      lib: {
        entry: fileURLToPath(new URL("./fixtures/chat-composer.tsx", import.meta.url)),
        formats: ["iife"],
        name: "ChatComposerFixture",
      },
    },
  });
  if ("on" in result) throw new Error("Composer fixture must be a one-off build");
  const chunk = (Array.isArray(result) ? result : [result])
    .flatMap((bundle) => bundle.output)
    .find((output) => output.type === "chunk" && output.isEntry);
  if (chunk?.type !== "chunk") throw new Error("Composer fixture entry is missing");
  composerScript = chunk.code;
});

test.beforeEach(async ({ page }) => {
  await page.setContent(`<style>${styles}</style><div id="root"></div>`);
  await page.addScriptTag({ content: composerScript });
});

for (const mobile of [false, true]) {
  test(`composer keeps a compact toolbar and seamless typing surface on ${mobile ? "mobile" : "desktop"}`, async ({ page }) => {
    await page.setViewportSize(mobile ? { width: 390, height: 844 } : { width: 1159, height: 964 });
    const input = page.getByRole("textbox", { name: "Message" });
    const toolbar = page.locator(".chat-composer-toolbar");
    const model = page.getByRole("button", { name: "Model and reasoning" });
    const send = page.getByRole("button", { name: "Send" });
    await expect.poll(async () => (await toolbar.boundingBox())!.height).toBeLessThanOrEqual(48);
    expect((await input.boundingBox())!.height).toBeGreaterThanOrEqual(80);
    expect((await model.boundingBox())!.height).toBe(mobile ? 44 : 36);
    expect((await send.boundingBox())!.height).toBe(44);
    expect((await send.boundingBox())!.width).toBe(44);
    await expect(input).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
    await expect(toolbar).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
    await input.fill("Investigate a low-volatility signal.");
    await expect(input).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
    await expect(input).toHaveCSS("border-bottom-width", "0px");
    await expect(toolbar).toHaveCSS("border-top-width", "0px");
    await expect(toolbar).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
    await expect(input).toHaveCSS("outline-style", "none");
    await expect(input).toHaveCSS("box-shadow", "none");
    await input.press("Tab");
    await expect(model).toBeFocused();
    await expect(input).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
    await expect(model).toHaveCSS("outline-width", "2px");
    await model.press("Tab");
    await expect(send).toBeFocused();
    await expect(send).toHaveCSS("outline-width", "2px");
    expect(await page.locator("body").evaluate((body) => body.scrollWidth <= window.innerWidth)).toBe(true);
  });

  test(`composer caps multiline drafts at 180px and shrinks after editing on ${mobile ? "mobile" : "desktop"}`, async ({ page }) => {
    await page.setViewportSize(mobile ? { width: 390, height: 844 } : { width: 1159, height: 964 });
    const input = page.getByRole("textbox", { name: "Message" });
    const height = async () => (await input.boundingBox())!.height;

    await input.fill("d");
    await expect.poll(height).toBe(80);
    await input.press("Shift+Enter");
    await input.pressSequentially("d");
    await expect(input).toHaveValue("d\nd");
    await expect.poll(height).toBe(80);

    const spacedDraft = `d${"\n".repeat(15)}d`;
    await input.fill(spacedDraft);
    await expect(input).toHaveValue(spacedDraft);
    await expect.poll(height).toBe(180);
    await expect(input).toHaveCSS("overflow-y", "auto");
    expect(await input.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(true);
    await input.press("ControlOrMeta+End");
    await expect.poll(() => input.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);

    const wrappedDraft = "Investigate quality and low volatility. ".repeat(100);
    await input.fill(wrappedDraft);
    await expect(input).toHaveValue(wrappedDraft);
    await expect.poll(height).toBe(180);

    // The CSS viewport limit must still apply on short screens without editing.
    await page.setViewportSize({ width: mobile ? 390 : 1159, height: 400 });
    await expect.poll(height).toBe(mobile ? 128 : 160);
    await expect(input).toHaveCSS("overflow-y", "auto");
    await page.setViewportSize(mobile ? { width: 390, height: 844 } : { width: 1159, height: 964 });
    await expect.poll(height).toBe(180);

    await input.fill("Short draft");
    await expect.poll(height).toBe(80);
    expect(await input.evaluate((element) => element.scrollHeight)).toBe(80);
    await input.fill("");
    await expect.poll(height).toBe(80);
    await expect(input).toHaveValue("");
    await expect(page.getByRole("button", { name: "Send", exact: true })).toBeDisabled();
  });
}
