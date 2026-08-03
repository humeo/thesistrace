import { expect, test } from "@playwright/test";

test("opens the runnable four-resource Core shell", async ({ page }) => {
  await page.goto("/core.html");

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
  await expect(page.getByRole("main").getByLabel("Resource outlet")).toBeAttached();
});
