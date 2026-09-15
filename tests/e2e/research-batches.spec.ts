import { expect, sameOriginHeaders, test } from "./auth-fixture";
import { controlWorker } from "./research-run-control";

type Batch = {
  id: string;
  status: string;
  items: Array<{ research_run_id: string; status: string }>;
};

test("Research Batches lists active work and cancels only the confirmed batch", async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  const created: string[] = [];
  controlWorker("pause", "batch-research-worker");
  async function admit(key: string, count: number): Promise<Batch> {
    const response = await page.request.post("/api/research-batches", {
      headers: sameOriginHeaders(),
      data: {
        request_id: `browser-batch-cancel-${key}`,
        batch_kind: "factor_evaluation",
        start_date: "2026-08-04", end_date: "2026-08-05",
        universe: "top300", neutralization: "none",
        factors: Array.from({ length: count }, (_, i) => ({ item_key: `${key}-${i + 1}`, formula: i === 0 ? "rank(close)" : "-rank(close)" })),
      },
    });
    expect(response.status(), await response.text()).toBe(202);
    const batch = await response.json() as Batch;
    created.push(batch.id);
    return batch;
  }
  async function get(id: string): Promise<Batch> {
    const response = await page.request.get(`/api/research-batches/${id}`);
    expect(response.status()).toBe(200);
    return response.json() as Promise<Batch>;
  }
  async function cancel(id: string) {
    const response = await page.request.post(`/api/research-batches/${id}/cancel`, {
      headers: sameOriginHeaders(), data: { request_id: `browser-cleanup-${id}` },
    });
    expect(response.status(), await response.text()).toBe(200);
  }
  try {
    const target = await admit("target", 2);
    const sibling = await admit("sibling", 1);
    const history = await admit("history", 1);
    await cancel(history.id);

    const firstResponse = await page.request.get("/api/research-batches?active_only=true&limit=1");
    expect(firstResponse.status()).toBe(200);
    const first = await firstResponse.json();
    expect(first.items.map((item: Batch) => item.id)).toEqual([sibling.id]);
    expect(first.next_cursor).toBeTruthy();
    const secondResponse = await page.request.get(`/api/research-batches?active_only=true&limit=1&cursor=${encodeURIComponent(first.next_cursor)}`);
    const second = await secondResponse.json();
    expect(second.items.map((item: Batch) => item.id)).toEqual([target.id]);
    expect(second.next_cursor).toBeNull();

    const childId = target.items[0]!.research_run_id;
    const childResponse = await page.request.get(`/api/research-runs/${childId}`);
    expect(await childResponse.json()).toMatchObject({ id: childId, batch_id: target.id });
    await page.goto(`/research-runs/${childId}`);
    await expect(page.getByRole("link", { name: "View batch", exact: true })).toHaveAttribute("href", `/research-runs/batches/${target.id}`);
    await expect(page.getByRole("button", { name: "Cancel", exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Cancel batch", exact: true }).click();
    const confirmation = page.getByRole("dialog", { name: "Cancel batch?" });
    await expect(confirmation).toContainText("2 unfinished research runs will be cancelled");
    await expect(confirmation).toContainText("target-1");
    await expect(confirmation).toContainText("target-2");
    await confirmation.getByRole("button", { name: "Keep batch" }).click();
    expect((await get(target.id)).status).toBe("queued");
    await page.getByRole("button", { name: "Cancel batch", exact: true }).click();
    await confirmation.getByRole("button", { name: "Cancel batch", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/research-runs/batches/${target.id}$`));
    await expect(page.getByRole("status")).toHaveText("Batch cancelled. Completed results are retained.");
    expect((await get(target.id)).items.map(item => item.status)).toEqual(["cancelled", "cancelled"]);
    expect((await get(sibling.id)).status).toBe("queued");

    await page.getByRole("link", { name: "Back to Batches" }).click();
    const batchRows = page.getByRole("table").getByRole("row");
    await expect(batchRows.filter({ hasText: sibling.id })).toContainText("Queued");
    await expect(batchRows.filter({ hasText: target.id })).toHaveCount(0);
    await expect(batchRows.filter({ hasText: history.id })).toHaveCount(0);
    await page.getByRole("button", { name: "All batches", exact: true }).click();
    await expect(batchRows.filter({ hasText: target.id })).toContainText("Cancelled");
    await expect(batchRows.filter({ hasText: history.id })).toContainText("Cancelled");
    await testInfo.attach("batch-list-desktop", { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(batchRows.filter({ hasText: sibling.id }).getByRole("button", { name: "Cancel batch" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await testInfo.attach("batch-list-mobile", { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });
  } finally {
    try {
      for (const id of created) {
        if ((await get(id)).status === "queued") await cancel(id);
      }
    } finally {
      controlWorker("unpause", "batch-research-worker");
    }
  }
});
