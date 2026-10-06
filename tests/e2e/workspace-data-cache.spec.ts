import { expect, openDataOverview, runAuthOperator, test } from "./auth-fixture";

test("Operator Dataset publication refreshes cached Data after a lost submission response", { tag: "@isolated" }, async ({ page, researcher }, testInfo) => {
  test.setTimeout(180_000);
  expect(runAuthOperator("assign-operator", "--researcher-id", researcher.id)).toMatchObject({
    status: "assigned",
    researcher_id: researcher.id,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await openDataOverview(page);
  const beforeResponse = await page.request.get("/api/data");
  expect(beforeResponse.status()).toBe(200);
  const before = await beforeResponse.json() as {
    data_through_session: string;
    generation_manifest_sha256: string;
  };
  expect(before.data_through_session).toBe("2026-08-05");

  const documents: string[] = [];
  const commands: Array<{ as_of: string; idempotency_key: string }> = [];
  const confirmations: string[] = [];
  page.on("request", request => {
    if (request.resourceType() === "document") documents.push(request.url());
    const url = new URL(request.url());
    if (request.method() === "GET" && url.pathname === "/api/operator/data/refreshes/dataset") {
      confirmations.push(url.searchParams.get("idempotency_key") ?? "");
    }
  });
  await page.route("**/api/operator/data/refreshes/dataset", async route => {
    if (route.request().method() !== "POST") return route.continue();
    const body = route.request().postDataJSON() as { as_of: string; idempotency_key: string };
    commands.push({ as_of: body.as_of, idempotency_key: body.idempotency_key });
    const accepted = await route.fetch();
    expect(accepted.status()).toBe(202);
    await route.abort("failed");
  });

  const sidebar = page.locator("#primary-navigation");
  await sidebar.getByRole("link", { name: "Operator", exact: true }).click();
  await page.getByRole("navigation", { name: "Operator Console sections" })
    .getByRole("link", { name: "Data", exact: true }).click();
  await page.getByRole("textbox", { name: "As-of", exact: true }).fill("2026-08-11");
  await page.getByRole("button", { name: "Review Refresh", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Refresh all data?", exact: true });
  await expect(dialog).toContainText("2026-08-11T18:00:00+08:00");
  await dialog.getByRole("button", { name: "Submit Refresh", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Dataset published", exact: true }))
    .toBeVisible({ timeout: 90_000 });
  expect(commands).toHaveLength(1);
  expect(commands[0]!.as_of).toBe("2026-08-11T18:00:00+08:00");
  expect(confirmations).toContain(commands[0]!.idempotency_key);
  await testInfo.attach("dataset-publication-desktop.png", {
    body: await page.screenshot(), contentType: "image/png",
  });

  let releaseData = (): void => {};
  const dataGate = new Promise<void>(resolve => { releaseData = resolve; });
  await page.route("**/api/data", async route => {
    await dataGate;
    await route.continue();
  });
  try {
    const nextSnapshot = page.waitForResponse(response => (
      new URL(response.url()).pathname === "/api/data"
      && response.request().method() === "GET"
    ));
    await Promise.all([
      page.waitForRequest(request => new URL(request.url()).pathname === "/api/data"),
      sidebar.getByRole("link", { name: "Data", exact: true }).click(),
    ]);
    await expect(page.getByRole("heading", { name: "Data", exact: true })).toBeVisible();
    await expect(page.getByText(new RegExp(`— ${before.data_through_session}$`)).first()).toBeVisible();
    releaseData();
    const response = await nextSnapshot;
    expect(response.status()).toBe(200);
    const after = await response.json() as typeof before;
    expect(after.data_through_session).toBe("2026-08-11");
    expect(after.generation_manifest_sha256).not.toBe(before.generation_manifest_sha256);
    await expect(page.getByText(/— 2026-08-11$/).first()).toBeVisible();
    expect(documents).toEqual([]);
    await testInfo.attach("refreshed-data-desktop.png", {
      body: await page.screenshot(), contentType: "image/png",
    });
  } finally {
    releaseData();
    await page.unroute("**/api/data");
  }
});
