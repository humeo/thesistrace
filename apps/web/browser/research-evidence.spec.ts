import { expect, test } from "@playwright/test";
import { completedStrategyRun as run } from "./fixtures/strategy-result";
import { buildProductFixture } from "./build-product-fixture";
import { defaultSimulationCosts } from "../src/research/simulationCosts";
import { builtinFrameworkModules } from "../src/research/frameworkModules";
import { emptyResearchDraft } from "../src/research/draft";

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
    await page.getByRole("button", { name: "More actions", exact: true }).click();
    await page.getByRole("menuitem", { name: "Delete Research", exact: true }).click();
    await expect(page.getByRole("alertdialog")).toContainText("DailyTracks will remain.");
    await expect(page.getByRole("alertdialog")).toContainText("Evidence <br/> & regression");
    await expect(page.getByRole("alertdialog").locator("br")).toHaveCount(0);
    await page.getByRole("button", { name: "Keep Research", exact: true }).click();
    await expect(page.getByRole("alertdialog")).not.toBeVisible();
    await expect(page.getByRole("button", { name: "More actions", exact: true })).toBeFocused();
    await expect(page.getByText("Trading events", { exact: true })).toHaveCount(1);
    await expect(page.getByRole("tab", { name: "Daily holdings", exact: true })).toHaveCount(1);
    await expect(page.getByText("No matching Orders records.")).toBeVisible();
  }
  await page.getByRole("tab", { name: "Daily holdings", exact: true }).click();
  await expect(page.getByText("Daily holdings were not recorded for this result.")).toBeVisible();
});

test("result draft options open on demand and preserve the result when dismissed", async ({ page }) => {
  const input = { research_kind: "strategy_backtest", strategy_mode: "framework", initial_cash_cny: "100000",
    costs: defaultSimulationCosts(), hypothesis: null, start_date: run.start_date, end_date: run.end_date,
    universe: "top300", modules: builtinFrameworkModules };
  await page.route("https://research-evidence.test/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    if (path === "/api/research-folders") return route.fulfill({ json: { items: [
      { id: "folder_default", name: "Default", is_default: true },
      { id: "folder_followup", name: "Follow-up", is_default: false },
    ], next_cursor: null } });
    return route.fulfill({ json: { ...run, input } });
  });
  await page.goto("https://research-evidence.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await expect(page.getByRole("combobox", { name: "Target Folder" })).not.toBeVisible();
  await page.getByRole("button", { name: "Use as draft", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Create a draft", exact: true });
  await expect(dialog.getByRole("combobox", { name: "Target Folder" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole("button", { name: "Use as draft", exact: true })).toBeFocused();
  await expect(page.getByRole("group", { name: "Strategy Summary", exact: true })).toBeVisible();
  expect(await page.evaluate(() => localStorage.length)).toBe(0);
  await page.evaluate(draft => localStorage.setItem("thesistrace.research-draft.test.folder_followup", JSON.stringify(draft)), {
    ...emptyResearchDraft(), formula: "local unsent formula", storageSchema: "research-draft/v7",
  });
  await page.getByRole("button", { name: "Use as draft", exact: true }).click();
  await dialog.getByRole("combobox", { name: "Target Folder" }).click();
  await page.getByRole("option", { name: "Follow-up", exact: true }).click();
  await dialog.getByRole("button", { name: "Create draft", exact: true }).click();
  const replacement = page.getByRole("alertdialog");
  await expect(replacement).toContainText("discard unexecuted browser changes");
  await replacement.getByRole("button", { name: "Keep current draft", exact: true }).click();
  await expect(dialog.getByRole("combobox", { name: "Target Folder" })).toContainText("Follow-up");
  expect(await page.evaluate(() => localStorage.getItem("thesistrace.research-draft.test.folder_followup"))).toContain("local unsent formula");
  await dialog.getByRole("button", { name: "Create draft", exact: true }).click();
  await replacement.getByRole("button", { name: "Replace draft", exact: true }).click();
  await expect(page).toHaveURL(/\/research\?folder=folder_followup$/);
  expect(await page.evaluate(() => localStorage.getItem("thesistrace.research-draft.test.folder_followup"))).toContain('"researchKind":"strategy_backtest"');
});
