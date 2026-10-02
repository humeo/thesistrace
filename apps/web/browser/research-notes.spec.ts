import { expect, test } from "./workbench-fixture";

test("Research notes keep long content and manual resizing within a bounded height", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto("/research?new");
  await page.getByRole("button", { name: "Factor Evaluation", exact: true }).click();
  const notes = page.getByRole("textbox", { name: "Research notes (optional)", exact: true });
  const multiline = Array.from({ length: 40 }, (_, index) => `Line ${index + 1}`).join("\n");
  await notes.fill(multiline);
  await expect(notes).toHaveValue(multiline);
  await expect(notes).toHaveCSS("max-height", "240px");
  await expect.poll(async () => (await notes.boundingBox())!.height).toBeLessThanOrEqual(240);
  expect(await notes.evaluate(element => element.scrollHeight > element.clientHeight)).toBe(true);

  await notes.fill("A short note");
  await notes.scrollIntoViewIfNeeded();
  const before = (await notes.boundingBox())!;
  await page.mouse.move(before.x + before.width - 4, before.y + before.height - 4);
  await page.mouse.down();
  await page.mouse.move(before.x + before.width + 100, before.y + before.height + 400, { steps: 10 });
  await page.mouse.up();
  const after = (await notes.boundingBox())!;
  expect(after.height).toBe(240);
  expect(after.width).toBe(before.width);
});

for (const locale of ["en", "zh-CN"] as const) {
  test(`Research notes show a warning only above 1024 Unicode characters (${locale})`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 960 });
    await page.addInitScript(language => localStorage.setItem("quantgrove.interface-language", language), locale);
    await page.goto("/research?new");
    await page.getByRole("button", { name: locale === "en" ? "Factor Evaluation" : "因子评估", exact: true }).click();
    const notes = page.getByRole("textbox", {
      name: locale === "en" ? "Research notes (optional)" : "研究备注（可选）", exact: true,
    });
    const warning = page.getByRole("alert").filter({ hasText: locale === "en"
      ? "Keep notes within 1,024 characters." : "备注不能超过 1,024 个字符。" });
    const counter = page.getByText(/\d+\s*\/\s*1024\s*(characters|个字符)/);
    await expect(warning).toHaveCount(0);
    await expect(counter).toHaveCount(0);

    await notes.fill("📚".repeat(1024));
    await expect(notes).toHaveAttribute("aria-invalid", "false");
    await expect(warning).toHaveCount(0);
    await expect(counter).toHaveCount(0);

    await notes.fill("📚".repeat(1025));
    await expect(notes).toHaveValue("📚".repeat(1025));
    await expect(notes).toHaveAttribute("aria-invalid", "true");
    await expect(warning).toBeVisible();
    await expect(notes).toHaveAccessibleDescription(locale === "en"
      ? "Keep notes within 1,024 characters." : "备注不能超过 1,024 个字符。");
    await expect(counter).toHaveCount(0);

    await notes.press("End");
    await notes.press("Backspace");
    await expect(notes).toHaveValue("📚".repeat(1024));
    await expect(notes).toHaveAttribute("aria-invalid", "false");
    await expect(warning).toHaveCount(0);
    await expect(notes).not.toHaveAttribute("aria-describedby");
  });
}
