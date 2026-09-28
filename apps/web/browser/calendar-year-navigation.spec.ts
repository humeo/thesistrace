import { expect, test } from "./workbench-fixture";

test("Research start date calendar can jump directly to an earlier year", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/research");

  await page.getByRole("button", { name: "Open start date calendar" }).click();
  const calendar = page.getByRole("dialog", { name: "Open start date calendar" });
  await expect(calendar).toBeVisible();

  await calendar.getByRole("button", { name: "Choose year" }).click();
  await expect(calendar.getByRole("group", { name: "Choose year" })).toBeVisible();
  await calendar.getByRole("button", { name: "2022", exact: true }).click();
  await expect(calendar.getByRole("grid", { name: "August 2022" })).toBeVisible();
  await calendar.getByRole("button", { name: "Monday, August 15th, 2022" }).click();
  await expect(page.getByRole("textbox", { name: "Research start date" })).toHaveValue("2022-08-15");
});
