import { expect, test, workbenchData } from "./workbench-fixture";

test("Research opens from the loaded Data snapshot without waiting for another data response", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto("/data");
  await expect(page.locator(".data-field-table")).toBeVisible();
  let release!: () => void;
  const responseAvailable = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/data", async route => {
    await responseAvailable;
    await route.fallback();
  });
  try {
    await page.getByRole("link", { name: "Research", exact: true }).click();
    await expect(page.getByRole("button", { name: "Factor Evaluation", exact: true })).toBeVisible();
  } finally {
    release();
  }
});

test("returning to Data keeps loaded fields visible without waiting for another response", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto("/data");
  const fields = page.locator(".data-field-table");
  await expect(fields).toBeVisible();
  await page.getByRole("link", { name: "Research", exact: true }).click();
  await expect(page.getByRole("button", { name: "Factor Evaluation", exact: true })).toBeVisible();

  let release!: () => void;
  const responseAvailable = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/data", async route => {
    await responseAvailable;
    await route.fallback();
  });
  try {
    await page.goBack();
    await expect(fields).toBeVisible();
  } finally {
    release();
  }
});

test("an authenticated identity change never displays the previous Researcher's cached Data", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  const first = "00000000-0000-4000-8000-000000000001";
  let researcherId = first;
  let release!: () => void;
  const nextDataAvailable = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/auth/get-session", route => route.fulfill({ json: {
    session: { id: "00000000-0000-4000-8000-000000000002" },
    user: { id: researcherId, email: "browser@example.test", name: "Browser", active: true },
  } }));
  await page.route("**/api/researcher/bootstrap", route => route.fulfill({ json: {
    researcher_id: researcherId, system_folders: { default: "folder_default", batch_research: "folder_batch_research" },
  } }));
  await page.route("**/api/data", async route => {
    if (researcherId === first) return route.fulfill({ json: workbenchData });
    await nextDataAvailable;
    await route.fulfill({ json: { ...workbenchData, market_coverage: { start: "2010-01-04", end: "2026-10-05" } } });
  });
  await page.goto("/data");
  const oldCoverage = page.getByText("2010-01-04 — 2026-08-13", { exact: true });
  await expect(oldCoverage).toBeVisible();
  const origin = await page.evaluate(() => performance.timeOrigin);
  const nextRead = page.waitForRequest("**/api/data");
  researcherId = "00000000-0000-4000-8000-000000000003";
  try {
    await page.evaluate(() => window.dispatchEvent(new Event("focus")));
    await nextRead;
    await expect(oldCoverage).toHaveCount(0);
  } finally {
    release();
  }
  await expect(page.getByText("2010-01-04 — 2026-10-05", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => performance.timeOrigin)).toBe(origin);
});

test("renamed Folders remain current on return while their list revalidates", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  const folders = [
    { id: "folder_default", name: "Default", is_default: true, created_at: "2026-08-01T00:00:00Z" },
    { id: "folder_signals", name: "Signals", is_default: false, created_at: "2026-08-01T00:00:00Z" },
  ];
  let blocked = false;
  let release!: () => void;
  const responseAvailable = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/research-folders**", async route => {
    if (route.request().method() === "PATCH") {
      folders[1].name = route.request().postDataJSON().name;
      return route.fulfill({ json: folders[1] });
    }
    if (blocked) await responseAvailable;
    return route.fulfill({ json: { items: folders, next_cursor: null } });
  });
  await page.goto("/research");
  const trigger = page.getByRole("button", { name: "Research Folders", exact: true });
  await trigger.click();
  await page.getByRole("menuitem", { name: "Signals Folder actions", exact: true }).click();
  await page.getByRole("menu", { name: "Signals Folder actions", exact: true }).getByRole("menuitem", { name: "Rename Folder", exact: true }).click();
  const form = page.getByRole("dialog", { name: "Rename Folder", exact: true });
  await form.getByRole("textbox", { name: "Folder name", exact: true }).fill("Momentum");
  await form.getByRole("button", { name: "Rename Folder", exact: true }).click();
  await expect(page.getByRole("menuitem", { name: "Momentum", exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await page.getByRole("link", { name: "Data", exact: true }).click();
  await expect(page.locator(".data-field-table")).toBeVisible();
  blocked = true;
  const refreshing = page.waitForRequest("**/api/research-folders");
  try {
    await page.getByRole("link", { name: "Research", exact: true }).click();
    await refreshing;
    await trigger.click();
    await expect(page.getByRole("menuitem", { name: "Momentum", exact: true })).toBeVisible();
    await expect(page.getByRole("menuitem", { name: "Signals", exact: true })).toHaveCount(0);
    const origin = await page.evaluate(() => performance.timeOrigin);
    await page.getByRole("menuitem", { name: "Momentum", exact: true }).click();
    await expect(trigger).toContainText("Momentum folder");
    expect(await page.evaluate(() => performance.timeOrigin)).toBe(origin);
  } finally {
    release();
  }
});
