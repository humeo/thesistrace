import { expect, test } from "@playwright/test";

test("uses the four-resource shell as the only active product", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/data$/);

  const navigation = page.getByRole("navigation", { name: "Product resources" });
  await expect(navigation.getByRole("link")).toHaveCount(4);
  for (const [name, path, heading] of [
    ["Data", "/data", "Data overview"],
    ["Definitions", "/definitions", "Definitions"],
    ["Research Runs", "/research-runs", "Research Runs"],
    ["Daily Tracks", "/daily-tracks", "Daily Tracks"],
  ] as const) {
    await navigation.getByRole("link", { name }).click();
    await expect(page).toHaveURL(new RegExp(`${path}$`));
    await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
    await expect(
      page.getByRole("navigation", { name: "Product resources" }).getByRole("link"),
    ).toHaveCount(4);
  }

  await expect(
    page.getByText(
      /研究工作台|login|hosted|workspace dashboard|operations ledger|raw json|download/i,
    ),
  ).toHaveCount(0);
  expect((await page.request.get("/core.html")).status()).toBe(404);
});

test("shows current data as a read-only resource", async ({ page }) => {
  await page.goto("/data");

  await expect(page.getByRole("heading", { name: "Data overview" })).toBeVisible();
  await expect(page.getByText("Data not ready")).toBeVisible();
  await expect(page.getByRole("button", { name: "Refresh ↻" })).toBeVisible();
  await expect(page.getByRole("button", { name: /update/i })).toHaveCount(0);
  await expect(page.getByText(/Release|Generation|operator|history/i)).toHaveCount(0);
  expect((await page.request.post("/api/data/update")).status()).toBe(404);
  expect((await page.request.get("/api/data/releases")).status()).toBe(404);
});

test("saves and reopens an incomplete nameless Definition", async ({ page }) => {
  await page.goto("/definitions");
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
    (request) =>
      request.method() === "GET" &&
      request.url() === stableUrl.replace("/definitions/", "/api/definitions/"),
  );
  await page.getByRole("button", { name: "Refresh" }).click();
  await detailRefresh;
  await expect(page.getByRole("status")).toHaveText("Refreshed.");

  await page.route(
    `**/api/definitions/${stableUrl.split("/").at(-1)}`,
    (route) => route.abort(),
    { times: 1 },
  );
  await page.getByRole("button", { name: "Refresh" }).click();
  await expect(page.getByRole("alert")).toHaveText("Research Definition unavailable");
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
    operands: [{ field_id: "price.close.adjusted" }, { literal: 20 }],
  });
  expect(JSON.stringify(submitted)).not.toContain("close_adj");
  await expect(page.getByRole("status")).toHaveText("Saved revision 1.");

  await page.reload();
  await expect(page.getByLabel("Alpha operator")).toHaveValue("ts_mean");
  await expect(page.getByLabel("Alpha field 1")).toHaveValue("price.close.adjusted");
  await expect(page.getByLabel("Alpha window 2")).toHaveValue("20");
});

test("keeps unsaved editor values after revision and structure errors", async ({ page }) => {
  await page.goto("/definitions");
  await page.getByRole("button", { name: "New Definition" }).click();
  await page.getByLabel("Definition name").fill("Original name");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("status")).toHaveText("Saved revision 1.");
  const definitionId = page.url().split("/").at(-1);

  await page.evaluate(async (id) => {
    const response = await fetch(`/api/definitions/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_revision: 1, name: "External edit" }),
    });
    if (!response.ok) throw new Error(`external edit failed: ${response.status}`);
  }, definitionId);

  await page.getByLabel("Definition name").fill("My unsaved name");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("alert")).toHaveText(
    "Definition changed elsewhere at revision 2. Your edits are unchanged.",
  );
  await expect(page.getByLabel("Definition name")).toHaveValue("My unsaved name");
  await page.getByRole("button", {
    name: "Discard my edits and load server version",
  }).click();
  await expect(page.getByLabel("Definition name")).toHaveValue("External edit");

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
  await expect(page.getByLabel("Alpha window 2")).toHaveValue("0");
});

test("saves one rejected Run action and shows actionable issues", async ({ page }) => {
  await page.goto("/definitions");
  await page.getByRole("button", { name: "New Definition" }).click();
  await page.getByLabel("Definition name").fill("Incomplete run");
  await page.getByRole("button", { name: "Run" }).click();

  await expect(page.getByRole("status")).toHaveText(
    "Run rejected after saving revision 1.",
  );
  await expect(page).toHaveURL(/\/definitions\/def_[a-f0-9]+$/);
  await expect(page.getByRole("list", { name: "Run validation issues" })).toContainText(
    "Alpha is required",
  );
  await expect(page.getByText("Revision 1", { exact: true })).toBeVisible();
});

test("replays the same Run request after its committed response is lost", async ({ page }) => {
  await page.goto("/definitions");
  await page.getByRole("button", { name: "New Definition" }).click();
  await page.getByLabel("Definition name").fill("Retry one logical run");

  const requestIds: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/api/definitions/run")) {
      requestIds.push(request.postDataJSON().request_id as string);
    }
  });
  await page.route(
    "**/api/definitions/run",
    async (route) => {
      await route.fetch();
      await route.abort("failed");
    },
    { times: 1 },
  );

  await page.getByRole("button", { name: "Run" }).click();
  await expect(page.getByRole("alert")).toHaveText(
    "Definition Run response was not received. Run again to retry the same action.",
  );
  await page.getByRole("button", { name: "Run" }).click();
  await expect(page.getByRole("status")).toHaveText(
    "Run rejected after saving revision 1.",
  );
  expect(requestIds).toHaveLength(2);
  expect(requestIds[0]).toBe(requestIds[1]);
});
