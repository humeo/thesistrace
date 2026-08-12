import { expect, test, type Locator, type Page, type TestInfo } from "@playwright/test";

test("current data supports one visible ResearchRun and DailyTrack journey", async ({ page }, testInfo) => {
  test.setTimeout(90_000);
  const responses: string[] = [];
  const externalRequests: string[] = [];
  page.on("request", (request) => {
    const hostname = new URL(request.url()).hostname;
    if (hostname !== "127.0.0.1" && hostname !== "localhost") {
      externalRequests.push(request.url());
    }
  });
  page.on("response", (response) => {
    if (response.url().includes("/api/")) {
      responses.push(`${response.status()} ${response.request().method()} ${response.url()}`);
    }
  });

  try {
    await page.goto("/data");
    await expect(page.getByRole("heading", { name: "Data overview" })).toBeVisible();
    await expect(page.getByText("Ready for research")).toBeVisible();
    await expect(page.getByText("2026-08-03")).toBeVisible();
    await expect(page.getByText("2026-08-11")).toHaveCount(2);
    await expect(page.getByRole("button", { name: "Refresh ↻" })).toBeVisible();
    await expectForbiddenProductInternalsToBeAbsent(page);

    await page.getByRole("link", { name: "Definitions" }).click();
    await page.getByRole("button", { name: "New Definition" }).click();
    await expect(
      page.getByText("Both dates are required to run; incomplete drafts can still be saved."),
    ).toBeVisible();
    await page.getByLabel("Definition name").fill("Browser Current Data Alpha");
    await page.getByLabel("Research start date").fill("2026-08-05");
    await page.getByLabel("Research end date").fill("2026-08-03");
    await page.getByRole("button", { name: "Add Alpha" }).click();
    await page.getByLabel("Alpha field 1").selectOption("price.close.adjusted");
    await page.getByLabel("Alpha field 2").selectOption("price.close.adjusted");
    await page.getByLabel("Universe").selectOption("top300");
    await page.getByLabel("Neutralization").selectOption("none");
    await page.getByLabel("Holdings count").fill("1");
    await page.getByLabel("Rebalance interval").fill("1");

    await expect(page.getByRole("button", { name: "Run", exact: true })).toBeDisabled();
    await expect(
      page.getByText("Research end date must not precede start date"),
    ).toBeVisible();
    const rejectedRuns = await page.request.get("/api/research-runs");
    expect(rejectedRuns.ok()).toBeTruthy();
    expect((await rejectedRuns.json()).items).toHaveLength(0);

    await page.getByLabel("Research start date").fill("2026-08-03");
    await page.getByLabel("Research end date").fill("2026-08-05");
    await page.getByRole("button", { name: "Run", exact: true }).click();
    await expect(page).toHaveURL(/\/research-runs\/run_[a-f0-9]+$/, {
      timeout: 30_000,
    });
    const sourceRunUrl = page.url();
    await expect(
      page.locator(".research-run-facts p").filter({ hasText: "Status" }),
    ).toContainText("succeeded", { timeout: 30_000 });
    await expect(page.getByRole("heading", { name: "Factor Summary" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Strategy Summary" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Daily Observations" })).toBeVisible();
    await expect(page.getByRole("table", { name: "Daily Observations" }).locator("tbody tr"))
      .toHaveCount(3);
    await expect(page.getByRole("heading", { name: "Terminal Strategy State" }))
      .toBeVisible();
    await expect(page.getByText("2026-08-05").first()).toBeVisible();
    const terminalSection = page.getByRole("region", { name: "Terminal Strategy State" });
    const terminalNav = await metricValue(terminalSection, "Net NAV");
    const terminalCash = await metricValue(terminalSection, "Net cash");
    await expectForbiddenProductInternalsToBeAbsent(page);

    await page.getByRole("button", { name: "Start Tracking" }).click();
    await expect(page).toHaveURL(/\/daily-tracks\/track_[a-f0-9]+$/, {
      timeout: 30_000,
    });
    await expect(page.getByRole("heading", { name: "Tracking Origin" })).toBeVisible();
    await expect(page.getByText(`Origin net NAV ${terminalNav}`, { exact: true })).toBeVisible();
    await expect(page.getByText(`Origin net cash ${terminalCash}`, { exact: true })).toBeVisible();

    await expect.poll(
      async () => {
        await page.getByRole("button", { name: "Refresh", exact: true }).click();
        return await page.locator(".research-run-facts").first().innerText();
      },
      { timeout: 30_000, intervals: [100, 250, 500, 1_000] },
    ).toContain("Up to date");
    await expect(page.getByText("Strategy session 2026-08-11", { exact: true })).toBeVisible();
    await expectForbiddenProductInternalsToBeAbsent(page);

    await page.goto(sourceRunUrl);
    await expect(page.getByRole("button", { name: "Use as Draft" })).toBeVisible();
    page.once("dialog", async (dialog) => {
      expect(dialog.message()).toBe("Replace the existing browser draft?");
      await dialog.accept();
    });
    await page.getByRole("button", { name: "Use as Draft" }).click();
    await expect(page).toHaveURL(/\/definitions$/);
    await expect(page.getByLabel("Definition name")).toHaveValue("Browser Current Data Alpha");
    await expect(page.getByLabel("Research start date")).toHaveValue("2026-08-03");
    await expect(page.getByLabel("Research end date")).toHaveValue("2026-08-05");
    await expect(page.getByLabel("Universe")).toHaveValue("top300");
    await expect(page.getByLabel("Neutralization")).toHaveValue("none");
    await page.getByLabel("Definition name").fill("Copied Browser Current Data Alpha");
    await page.reload();
    await expect(page.getByLabel("Definition name")).toHaveValue(
      "Copied Browser Current Data Alpha",
    );
    await page.getByRole("button", { name: "Run", exact: true }).click();
    await expect(page).toHaveURL(/\/research-runs\/run_[a-f0-9]+$/, {
      timeout: 30_000,
    });
    expect(page.url()).not.toBe(sourceRunUrl);
    await expect(
      page.locator(".research-run-facts p").filter({ hasText: "Status" }),
    ).toContainText("succeeded", { timeout: 30_000 });
    expect(externalRequests, "browser journey must remain local-only").toEqual([]);
  } finally {
    await attachResponses(testInfo, responses);
    await testInfo.attach("external-requests.json", {
      body: Buffer.from(`${JSON.stringify(externalRequests, null, 2)}\n`, "utf8"),
      contentType: "application/json",
    });
  }
});

async function metricValue(scope: Locator, label: string): Promise<string> {
  const metric = scope.locator(".result-metric").filter({ hasText: label });
  return (await metric.locator("strong").innerText()).trim();
}

async function expectForbiddenProductInternalsToBeAbsent(page: Page): Promise<void> {
  const body = await page.locator("body").innerText();
  expect(body).not.toMatch(
    /Update data|Dataset Release|Data Generation|operator attempt|manifest location|checkpoint manifest|pin fence/i,
  );
}

async function attachResponses(testInfo: TestInfo, responses: string[]): Promise<void> {
  await testInfo.attach("api-responses.txt", {
    body: Buffer.from(`${responses.join("\n")}\n`, "utf8"),
    contentType: "text/plain",
  });
}
