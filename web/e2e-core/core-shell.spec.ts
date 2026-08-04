import { expect, test } from "@playwright/test";

test("publishes the first Dataset Release through the real Core", async ({ page }) => {
  test.setTimeout(90_000);
  await page.goto("/data");

  const navigation = page.getByRole("navigation", { name: "Product resources" });
  await expect(navigation.getByRole("link")).toHaveCount(4);
  await expect(navigation.getByRole("link", { name: "Data" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await expect(navigation.getByRole("link", { name: "Definitions" })).toHaveAttribute(
    "href",
    "/definitions",
  );
  await expect(navigation.getByRole("link", { name: "Research Runs" })).toHaveAttribute(
    "href",
    "/research-runs",
  );
  await expect(navigation.getByRole("link", { name: "Daily Tracks" })).toHaveAttribute(
    "href",
    "/daily-tracks",
  );
  await expect(page.getByText("No Dataset Releases yet.")).toBeVisible();
  await page.getByRole("button", { name: "Update Data" }).click();
  await expect(page.getByRole("status")).toHaveText("Updating canonical data…");
  await expect(page.getByRole("heading", { name: "Latest Dataset Release" })).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByText("756 Research Sessions")).toBeVisible();
  await expect(page.getByText("First Release")).toBeVisible();
  const firstRelease = await page
    .getByRole("list", { name: "Dataset Release history" })
    .getByRole("listitem")
    .first()
    .textContent();
  await page.getByRole("button", { name: "Update Data" }).click();
  await expect(page.getByRole("status")).toHaveText("Updating canonical data…");
  await expect(page.getByText("757 Research Sessions")).toBeVisible({ timeout: 30_000 });
  const releaseHistory = page.getByRole("list", { name: "Dataset Release history" });
  await expect(releaseHistory.getByRole("listitem")).toHaveCount(2);
  await expect(releaseHistory).toContainText(firstRelease ?? "missing-root-release");
  await expect(page.getByText("Later Release")).toBeVisible();
  const latestRelease = await page
    .getByRole("heading", { name: "Latest Dataset Release" })
    .locator("..")
    .textContent();
  await page.getByRole("button", { name: "Update Data" }).click();
  await expect(page.getByRole("status")).toHaveText("Updating canonical data…");
  await expect(page.getByRole("status")).toHaveText(
    "No new completed Research Session. Latest Release unchanged.",
    { timeout: 30_000 },
  );
  await expect(releaseHistory.getByRole("listitem")).toHaveCount(2);
  await expect(
    page.getByRole("heading", { name: "Latest Dataset Release" }).locator(".."),
  ).toHaveText(latestRelease ?? "missing-latest-release");
  await expect(page.getByText("manifest_sha256")).toHaveCount(0);
  await expect(page.getByText("object_key")).toHaveCount(0);
});

test("saves and reopens an incomplete nameless Definition", async ({ page }) => {
  await page.goto("/definitions");

  await expect(page.getByRole("heading", { name: "Definitions" })).toBeVisible();
  await expect(page.getByText("No Research Definitions yet.")).toBeVisible();
  await page.getByRole("button", { name: "New Definition" }).click();
  await expect(page.getByLabel("Definition name")).toHaveValue("");
  await expect(page.getByLabel("Hypothesis (optional)")).toHaveValue("");
  await page.getByRole("button", { name: "Save" }).click();

  await expect(page.getByRole("status")).toHaveText("Saved revision 1.");
  const generatedName = await page.getByLabel("Definition name").inputValue();
  expect(generatedName).not.toBe("");
  await expect(page).toHaveURL(/\/definitions\/def_[a-f0-9]+$/);
  const stableUrl = page.url();

  const detailRefresh = page.waitForRequest(
    (request) => request.method() === "GET" && request.url() === stableUrl.replace("/definitions/", "/api/definitions/"),
  );
  await page.getByRole("button", { name: "Refresh" }).click();
  await detailRefresh;
  await expect(page.getByRole("status")).toHaveText("Refreshed.");

  await page.route(`**/api/definitions/${stableUrl.split("/").at(-1)}`, (route) =>
    route.abort(), { times: 1 });
  await page.getByRole("button", { name: "Refresh" }).click();
  await expect(page.getByRole("alert")).toHaveText("Research Definition unavailable");
  await expect(page.getByRole("status")).toHaveCount(0);
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);

  await page.getByLabel("Hypothesis (optional)").fill("Temporary hypothesis");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("status")).toHaveText("Saved revision 2.");
  await page.getByLabel("Hypothesis (optional)").fill("");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("status")).toHaveText("Saved revision 3.");

  await page.reload();
  await expect(page.getByLabel("Definition name")).toHaveValue(generatedName);
  await expect(page.getByText("Revision 3")).toBeVisible();
  await expect(page.getByLabel("Hypothesis (optional)")).toHaveValue("");
  await page.getByRole("link", { name: "Definitions" }).click();
  await expect(page.getByRole("link", { name: generatedName })).toBeVisible();
  await page.getByRole("button", { name: "Refresh" }).click();
  await page.getByRole("link", { name: generatedName }).click();
  await expect(page).toHaveURL(stableUrl);
  await expect(page.getByLabel("Hypothesis (optional)")).toHaveValue("");
  await expect(page.getByText(/Draft|Snapshot|Frozen version/i)).toHaveCount(0);
});

test("authors and reopens an Alpha using authoritative stable IDs", async ({ page }) => {
  await page.goto("/definitions");
  await page.getByRole("button", { name: "New Definition" }).click();
  await page.getByRole("button", { name: "Add Alpha" }).click();

  await page.getByLabel("Alpha operator").selectOption("ts_mean");
  await page.getByLabel("Alpha field 1").selectOption("price.close.adjusted");
  await page.getByLabel("Alpha window 2").fill("20");
  await page.getByLabel("Universe").selectOption("top1000");
  await page.getByLabel("Neutralization").selectOption("industry");
  await page.getByLabel("Holdings count").fill("30");
  await page.getByLabel("Rebalance interval").fill("5");

  const saveRequest = page.waitForRequest(
    (request) => request.method() === "POST" && request.url().endsWith("/api/definitions"),
  );
  await page.getByRole("button", { name: "Save" }).click();
  const submitted = (await saveRequest).postDataJSON();
  expect(submitted.alpha).toEqual({
    operator_id: "ts_mean",
    operands: [
      { field_id: "price.close.adjusted" },
      { literal: 20 },
    ],
  });
  expect(JSON.stringify(submitted)).not.toContain("close_adj");
  await expect(page.getByRole("status")).toHaveText("Saved revision 1.");

  await page.reload();
  await expect(page.getByLabel("Alpha operator")).toHaveValue("ts_mean");
  await expect(page.getByLabel("Alpha field 1")).toHaveValue("price.close.adjusted");
  await expect(page.getByLabel("Alpha window 2")).toHaveValue("20");
  await expect(page.getByLabel("Universe")).toHaveValue("top1000");
  await expect(page.getByLabel("Neutralization")).toHaveValue("industry");
  await expect(page.getByLabel("Holdings count")).toHaveValue("30");
  await expect(page.getByLabel("Rebalance interval")).toHaveValue("5");
});

test("keeps unsaved editor values after revision and structure errors", async ({ page }) => {
  await page.goto("/definitions");
  await page.getByRole("button", { name: "New Definition" }).click();
  await page.getByLabel("Definition name").fill("Original name");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("status")).toHaveText("Saved revision 1.");
  const definitionId = page.url().split("/").at(-1);
  expect(definitionId).toMatch(/^def_[a-f0-9]+$/);

  await page.evaluate(async (id) => {
    const response = await fetch(`/api/definitions/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_revision: 1, name: "External edit" }),
    });
    if (!response.ok) throw new Error(`external edit failed: ${response.status}`);
  }, definitionId);

  await page.getByLabel("Definition name").fill("My unsaved name");
  await page.getByLabel("Hypothesis (optional)").fill("My unsaved hypothesis");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("alert")).toHaveText(
    "Definition changed elsewhere at revision 2. Your edits are unchanged.",
  );
  await expect(page.getByLabel("Definition name")).toHaveValue("My unsaved name");
  await expect(page.getByLabel("Hypothesis (optional)")).toHaveValue(
    "My unsaved hypothesis",
  );
  await expect(page.getByText("Revision 1")).toBeVisible();

  await page.getByRole("button", { name: "Add Alpha" }).click();
  await page.getByLabel("Alpha operator").selectOption("ts_mean");
  await page.getByLabel("Alpha window 2").evaluate((element) => {
    element.removeAttribute("min");
  });
  await page.getByLabel("Alpha window 2").fill("0");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("alert")).toHaveText(
    "Definition has structural errors. Your edits are unchanged.",
  );
  await expect(page.getByLabel("Definition name")).toHaveValue("My unsaved name");
  await expect(page.getByLabel("Hypothesis (optional)")).toHaveValue(
    "My unsaved hypothesis",
  );
  await expect(page.getByLabel("Alpha window 2")).toHaveValue("0");
});
