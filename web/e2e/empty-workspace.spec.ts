import { expect, test } from "@playwright/test";

test("shows the real empty workspace and dependency health", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "研究工作台" })).toBeVisible();
  await expect(page.getByText("尚未发布数据版本")).toBeVisible();
  await expect(
    page.getByRole("group", { name: "Dataset Releases" }).getByText("0", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("group", { name: "Research Runs" }).getByText("0", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("API / Metadata")).toBeVisible();
  await expect(page.getByText("Object Store")).toBeVisible();
  await expect(page.getByText("Worker")).toBeVisible();
  await expect(page.getByText("没有伪造示例资源")).toBeVisible();

  await page.getByRole("button", { name: "发布 Fixture Bootstrap" }).click();

  await expect(page.getByRole("heading", { name: "Fixture Bootstrap 已发布" })).toBeVisible();
  await expect(page.getByText("756 sessions")).toBeVisible();
  await expect(page.getByText("ROOT", { exact: true })).toBeVisible();
  await expect(page.getByText("2 immutable objects")).toBeVisible();
});
