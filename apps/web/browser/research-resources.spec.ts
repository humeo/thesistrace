import { expect, test } from "@playwright/test";
import { buildProductFixture } from "./build-product-fixture";

let timelineScript: string;
let styles: string;

test.beforeAll(async () => {
  ({ script: timelineScript, styles } = await buildProductFixture(new URL("./fixtures/research-resources.tsx", import.meta.url), "ChatTimelineFixture"));
});


test("A2UI resource references read Core and isolate an unavailable sibling", async ({ page }) => {
  let status = "running";
  await page.route("http://research.test/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    if (path.endsWith("run_1123456789abcdef0123")) return route.fulfill({ status: 404 });
    const result = status === "succeeded" ? { factor: { horizons: Object.fromEntries(["1", "5", "20"].map(h => [h, { summary: { rank_ic: { mean: 0.125 } } }])) } } : undefined;
    return route.fulfill({ json: { id: "run_0123456789abcdef0123", name: "Core research", status, formula_summary: "rank(close)", start_date: "2026-01-01", end_date: "2026-08-27", research_kind: "factor_evaluation", ...(result ? { result } : {}) } });
  });
  await page.goto("http://research.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: timelineScript });
  await expect(page.getByRole("heading", { name: "Core research" })).toBeVisible();
  await expect(page.getByRole("alert")).toContainText("Resource unavailable or access denied");
  await expect(page.getByText("Results are available after this research succeeds.")).toBeVisible();
  status = "succeeded";
  await page.getByRole("button", { name: "Reload view" }).first().click();
  await expect(page.getByText("0.125", { exact: true })).toHaveCount(3);
  await expect(page.getByText("running · Factor Evaluation")).toHaveCount(0);
});
