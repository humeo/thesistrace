import { expect, test } from "./workbench-fixture";

test("research entry focuses its heading without a frame and keeps keyboard choice feedback", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto("/research");
  const heading = page.getByRole("heading", { name: "Choose a research type", exact: true });
  await expect(heading).toBeFocused();
  await expect(heading).toHaveCSS("outline-style", "none");
  await page.reload();
  await expect(heading).toBeFocused();
  await expect(heading).toHaveCSS("outline-style", "none");

  await page.keyboard.press("Tab");
  const factor = page.getByRole("button", { name: "Factor Evaluation", exact: true });
  await expect(factor).toBeFocused();
  await expect(factor).not.toHaveCSS("box-shadow", "none");
  await factor.press("Enter");
  await expect(page.getByRole("button", { name: "Run evaluation", exact: true })).toBeVisible();
});
