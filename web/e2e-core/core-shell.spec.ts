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
  await expect(page.getByText("manifest_sha256")).toHaveCount(0);
  await expect(page.getByText("object_key")).toHaveCount(0);
});
