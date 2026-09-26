import { expect, test } from "./auth-fixture";

test("Research Batch return keeps server cursor and All filter without document reload", async ({ page }) => {
  const base = { batch_kind: "factor_evaluation", status: "succeeded", created_at: "2026-09-15T00:00:00Z",
    scope: { start_date: "2026-08-04", end_date: "2026-08-05", universe: "top300", neutralization: "none" },
    progress: { completed_factor_tasks: 1, total_factor_tasks: 1 }, live_progress: null, items: [{ ordinal: 1, item_key: "Completed factor", research_run_id: "run_complete", status: "succeeded", run_availability: "available" }],
  };
  const queries: URLSearchParams[] = [];
  await page.route("**/api/research-batches?**", route => {
    const query = new URL(route.request().url()).searchParams;
    queries.push(query);
    return route.fulfill({ json: { items: [{ ...base, id: query.has("cursor") ? "batch_bbbbbbbbbbbbbbbbbbbb" : "batch_aaaaaaaaaaaaaaaaaaaa" }], next_cursor: query.has("cursor") ? null : "second" } });
  });
  await page.route("**/api/research-batches/batch_bbbbbbbbbbbbbbbbbbbb", route => route.fulfill({ json: { ...base, id: "batch_bbbbbbbbbbbbbbbbbbbb" } }));
  await page.goto("/research-runs/batches");
  await page.getByRole("button", { name: "All batches", exact: true }).click();
  const pages = page.getByRole("navigation", { name: "Batch pages", exact: true });
  await pages.getByRole("button", { name: "Next", exact: true }).click();
  await expect(pages).toContainText("Page 2");
  await page.getByRole("link").filter({ hasText: "batch_bbbbbbbbbbbbbbbbbbbb" }).click();
  await expect(page).toHaveURL(/\/research-runs\/batches\/batch_bbbbbbbbbbbbbbbbbbbb$/);
  const documents: string[] = [];
  page.on("request", request => { if (request.resourceType() === "document") documents.push(request.url()); });
  await page.getByRole("link", { name: "Back to Batches", exact: true }).click();
  await expect(pages).toContainText("Page 2");
  await expect(page.getByRole("button", { name: "All batches", exact: true })).toHaveAttribute("aria-pressed", "true");
  expect(queries.at(-1)?.get("cursor")).toBe("second");
  expect(queries.at(-1)?.get("active_only")).toBe("false");
  expect(documents).toEqual([]);
});
