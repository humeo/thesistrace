import { expect, test } from "@playwright/test";
import { completedStrategyRun as run } from "./fixtures/strategy-result";
import { buildProductFixture } from "./build-product-fixture";

let script: string;
let styles: string;
test.beforeAll(async () => {
  ({ script, styles } = await buildProductFixture(new URL("./fixtures/research-evidence.tsx", import.meta.url), "ResearchEvidenceFixture"));
});

// Shared deterministic result facts; request behavior remains local to each test.


test("ResearchRun updates preserve one working events and holdings section", async ({ page }) => {
  await page.route("https://research-evidence.test/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    if (path === "/api/research-folders") return route.fulfill({ json: {
      items: [{ id: "folder_default", name: "Default", is_default: true }], next_cursor: null,
    } });
    if (path.endsWith("/events/query")) return route.fulfill({ json: {
      section: route.request().postDataJSON().section, status: "recorded", rows: [], next_cursor: null,
    } });
    if (path.endsWith("/holdings/query")) return route.fulfill({ json: { status: "not_recorded", units: [], next_cursor: null } });
    return route.fulfill({ json: run });
  });
  await page.goto("https://research-evidence.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await expect(page.getByText("Trading events", { exact: true })).toHaveCount(1);
  await page.getByText("Trading events", { exact: true }).click();
  await expect(page.getByText("No matching Orders records.")).toBeVisible();
  // Opening and dismissing the confirmation only updates the actual parent page;
  // it must not replace these independent sections or leave orphaned DOM nodes.
  for (let i = 0; i < 3; i++) {
    await page.getByRole("banner").getByRole("button", { name: "Delete Research", exact: true }).click();
    await expect(page.getByRole("alertdialog")).toContainText("DailyTracks will remain.");
    await expect(page.getByRole("alertdialog")).toContainText("Evidence <br/> & regression");
    await expect(page.getByRole("alertdialog").locator("br")).toHaveCount(0);
    await page.getByRole("button", { name: "Keep Research", exact: true }).click();
    await expect(page.getByRole("alertdialog")).not.toBeVisible();
    await expect(page.getByText("Trading events", { exact: true })).toHaveCount(1);
    await expect(page.getByRole("tab", { name: "Daily holdings", exact: true })).toHaveCount(1);
    await expect(page.getByText("No matching Orders records.")).toBeVisible();
  }
  await page.getByRole("tab", { name: "Daily holdings", exact: true }).click();
  await expect(page.getByText("Daily holdings were not recorded for this result.")).toBeVisible();
});
