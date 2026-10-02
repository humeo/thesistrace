import { expect, test } from "./workbench-fixture";

test("Research start date calendar can jump directly to an earlier year", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/research");
  await page.getByRole("button", { name: "Factor Evaluation", exact: true }).click();
  await page.getByRole("button", { name: "Evaluation conditions", exact: true }).click();

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

test("Research date calendar can select a month directly", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/research");
  await page.getByRole("button", { name: "Factor Evaluation", exact: true }).click();
  await page.getByRole("button", { name: "Evaluation conditions", exact: true }).click();
  await page.getByRole("button", { name: "Open start date calendar" }).click();
  const calendar = page.getByRole("dialog", { name: "Open start date calendar" });
  await calendar.getByRole("button", { name: "Choose year", exact: true }).click();
  await calendar.getByRole("button", { name: "2022", exact: true }).click();
  await calendar.getByRole("combobox", { name: "Choose month", exact: true }).click();
  await page.getByRole("option", { name: "March", exact: true }).click();
  await expect(calendar.getByRole("grid", { name: "March 2022" })).toBeVisible();
  await calendar.getByRole("button", { name: "Tuesday, March 15th, 2022" }).click();
  await expect(page.getByRole("textbox", { name: "Research start date" })).toHaveValue("2022-03-15");
});
