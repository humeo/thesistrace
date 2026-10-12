import type { Page } from "@playwright/test";
import { expect, test } from "./workbench-fixture";
import { completedStrategyRun } from "./fixtures/strategy-result";

const first = { ...completedStrategyRun, id: "run_abcd1234", name: "First research" };
const second = { ...completedStrategyRun, id: "run_dcba1234", name: "Second research" };

async function setupResearchRuns(page: Page, deletions: string[]): Promise<void> {
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.route("**/api/research-runs?*", route => route.fulfill({ json: {
    items: [first, second].filter(run => !deletions.includes(run.id)),
    total_count: 2 - deletions.length,
  } }));
  for (const run of [first, second]) await page.route(`**/api/research-runs/${run.id}`, route => {
    if (route.request().method() === "DELETE") {
      deletions.push(run.id);
      return route.fulfill({ status: 204 });
    }
    return route.fulfill({ json: run });
  });
}

test("a successful Research deletion clears its confirmation before another run opens", async ({ page }) => {
  const deletions: string[] = [];
  await setupResearchRuns(page, deletions);
  await page.goto(`/research-runs/${first.id}`);
  await page.getByRole("button", { name: "More actions", exact: true }).click();
  await page.getByRole("menuitem", { name: "Delete Research", exact: true }).click();
  const decision = page.getByRole("alertdialog", { name: "Delete Research?" });
  await expect(decision).toContainText(first.name);
  await decision.getByRole("button", { name: "Delete Research", exact: true }).click();
  await expect(page).toHaveURL(/\/research-runs$/);
  await page.getByRole("link", { name: second.name, exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/research-runs/${second.id}$`));
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: second.name, exact: true })).toBeVisible();
  expect(deletions).toEqual([first.id]);
});

test("a delete confirmation is cleared when history navigation opens another ResearchRun", async ({ page }) => {
  const deletions: string[] = [];
  await setupResearchRuns(page, deletions);
  await page.goto("/research-runs");
  await page.getByRole("link", { name: first.name, exact: true }).click();
  await page.getByRole("button", { name: "More actions", exact: true }).click();
  await page.getByRole("menuitem", { name: "Delete Research", exact: true }).click();
  await expect(page.getByRole("alertdialog", { name: "Delete Research?" })).toContainText(first.name);
  await page.goBack();
  await page.getByRole("link", { name: second.name, exact: true }).click();
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: second.name, exact: true })).toBeVisible();
  expect(deletions).toEqual([]);
});
