import { expect, test } from "@playwright/test";

test("publishes the first Dataset Release through the real Core", async ({ page }) => {
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

  await page.reload();
  await expect(page.getByLabel("Definition name")).toHaveValue(generatedName);
  await expect(page.getByText("Revision 1")).toBeVisible();
  await page.getByRole("link", { name: "Definitions" }).click();
  await expect(page.getByRole("link", { name: generatedName })).toBeVisible();
  await page.getByRole("button", { name: "Refresh" }).click();
  await page.getByRole("link", { name: generatedName }).click();
  await expect(page).toHaveURL(stableUrl);
  await expect(page.getByLabel("Hypothesis (optional)")).toHaveValue("");
  await expect(page.getByText(/Draft|Snapshot|Frozen version/i)).toHaveCount(0);
});
