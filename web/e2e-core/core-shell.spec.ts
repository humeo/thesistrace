import { expect, test, type Page, type TestInfo } from "@playwright/test";

test("Default Folder retains one local Research Draft with authoritative Formula diagnostics", async ({ page }, testInfo) => {
  test.setTimeout(90_000);
  const responses: string[] = [];
  const externalRequests: string[] = [];
  page.on("request", (request) => {
    const hostname = new URL(request.url()).hostname;
    if (hostname !== "127.0.0.1" && hostname !== "localhost") externalRequests.push(request.url());
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

    await page.getByRole("link", { name: "New Research", exact: true }).click();
    await expect(page).toHaveURL(/\/research$/);
    await expect(page.getByRole("heading", { name: "Research", exact: true })).toBeVisible();
    await expect(page.getByText("Default Folder")).toBeVisible();
    await expect(page.getByLabel("Research name")).toHaveValue("");
    await expect(page.locator(".cm-content")).toHaveText("");
    await expectRemovedAuthoringControlsToBeAbsent(page);

    await page.getByLabel("Research name").fill("Browser Mean Research");
    const editor = page.locator(".cm-content");
    await editor.click();
    await page.keyboard.type("ts_");
    await page.keyboard.press("Control+Space");
    const meanCompletion = page.getByRole("option", { name: /ts_mean/ });
    await expect(meanCompletion).toBeVisible();
    await expect(page.locator(".cm-completionInfo")).toContainText("Complete-window rolling");
    await page.keyboard.press("Escape");
    await page.keyboard.press(process.platform === "darwin" ? "Meta+A" : "Control+A");
    await page.keyboard.type("unknown_field");
    await expect(page.getByRole("list", { name: "Formula diagnostics" })).toBeVisible();
    await expect(page.locator(".cm-lintRange-error")).toHaveCount(1);
    await page.keyboard.press(process.platform === "darwin" ? "Meta+A" : "Control+A");
    await page.keyboard.type("ts_mean(close_adj, 2)");
    await expect(page.getByText("Valid formula", { exact: true })).toBeVisible();
    await page.getByLabel("Hypothesis").fill("Short rolling mean retains signal.");
    await page.getByLabel("Research start date").fill("2026-08-03");
    await page.getByLabel("Research end date").fill("2026-08-05");
    await page.getByLabel("Universe").selectOption("top300");
    await page.getByLabel("Neutralization").selectOption("none");
    await page.getByLabel("Holdings count").fill("10");
    await page.getByLabel("Rebalance sessions").fill("2");

    const browserKeys = await page.evaluate(() => Object.keys(localStorage));
    expect(browserKeys).toEqual(["thesistrace.research-draft.folder_default"]);
    const retainedDraft = await page.evaluate(() => JSON.parse(
      localStorage.getItem("thesistrace.research-draft.folder_default") ?? "null",
    ));
    expect(retainedDraft).toMatchObject({
      name: "Browser Mean Research",
      formula: "ts_mean(close_adj, 2)",
      universe: "top300",
      neutralization: "none",
      holdingsCount: "10",
      rebalanceEverySessions: "2",
      lastAdmittedBaseline: null,
    });

    await page.reload();
    await expect(page.getByLabel("Research name")).toHaveValue("Browser Mean Research");
    await expect(page.locator(".cm-content")).toHaveText("ts_mean(close_adj, 2)");
    await expect(page.getByLabel("Hypothesis")).toHaveValue("Short rolling mean retains signal.");
    await expect(page.getByLabel("Universe")).toHaveValue("top300");

    page.once("dialog", async (dialog) => dialog.dismiss());
    const workspaceNew = page.locator(".research-workspace-header").getByRole("button", { name: "New Research" });
    await workspaceNew.click();
    await expect(page.getByLabel("Research name")).toHaveValue("Browser Mean Research");
    page.once("dialog", async (dialog) => dialog.accept());
    await workspaceNew.click();
    await expect(page.getByLabel("Research name")).toHaveValue("");
    await expect(page.locator(".cm-content")).toHaveText("");
    expect(await page.evaluate(() => localStorage.getItem("thesistrace.research-draft.folder_default"))).toBeNull();

    await page.getByLabel("New Folder").fill("Signals");
    await page.getByRole("button", { name: "Create" }).click();
    await expect(page).toHaveURL(/\/research\?folder=folder_[a-f0-9]+$/);
    const customFolderId = new URL(page.url()).searchParams.get("folder");
    expect(customFolderId).toMatch(/^folder_[a-f0-9]+$/);
    if (customFolderId === null) throw new Error("Custom Folder route is missing folder id");
    await expect(page.getByText("Signals", { exact: true }).first()).toBeVisible();
    await page.getByLabel("Research name").fill("Signals browser Draft");
    await page.locator(".cm-content").click();
    await page.keyboard.type("volume_shares");

    page.once("dialog", async (dialog) => dialog.dismiss());
    await workspaceNew.click();
    await expect(page.getByLabel("Research name")).toHaveValue("Signals browser Draft");

    await page.getByRole("link", { name: "New Research", exact: true }).click();
    await expect(page).toHaveURL(/\/research$/);
    await expect(page.getByLabel("Research name")).toHaveValue("");
    expect(await page.evaluate((folderId) => localStorage.getItem(`thesistrace.research-draft.${folderId}`), customFolderId)).not.toBeNull();
    await page.getByRole("link", { name: "Signals", exact: true }).click();
    await expect(page.getByLabel("Research name")).toHaveValue("Signals browser Draft");
    await expect(page.locator(".cm-content")).toHaveText("volume_shares");
    expect(await page.evaluate(() => Object.keys(localStorage).sort())).toEqual([
      `thesistrace.research-draft.${customFolderId}`,
    ]);

    await page.getByLabel("Folder name").fill("Momentum");
    await page.getByRole("button", { name: "Rename Folder" }).click();
    await expect(page.getByRole("link", { name: "Momentum", exact: true })).toBeVisible();
    await expect(page.getByLabel("Research name")).toHaveValue("Signals browser Draft");

    const protectedDefault = await page.request.delete("/api/research-folders/folder_default");
    expect(protectedDefault.status()).toBe(409);
    page.once("dialog", async (dialog) => dialog.dismiss());
    await page.getByRole("button", { name: "Delete Folder" }).click();
    await expect(page.getByRole("link", { name: "Momentum", exact: true })).toBeVisible();
    page.once("dialog", async (dialog) => dialog.accept());
    await page.getByRole("button", { name: "Delete Folder" }).click();
    await expect(page).toHaveURL(/\/research$/);
    await expect(page.getByRole("link", { name: "Momentum", exact: true })).toHaveCount(0);
    expect(await page.evaluate((folderId) => localStorage.getItem(`thesistrace.research-draft.${folderId}`), customFolderId)).toBeNull();

    const folderRead = await page.request.get("/api/research-folders");
    expect(folderRead.ok()).toBeTruthy();
    expect((await folderRead.json()).items).toMatchObject([
      { id: "folder_default", name: "Default", is_default: true },
    ]);
    expect(responses.some((entry) => entry.includes("/api/definitions"))).toBe(false);
    expect(externalRequests, "browser journey must remain local-only").toEqual([]);
  } finally {
    await attachResponses(testInfo, responses);
  }
});

async function expectRemovedAuthoringControlsToBeAbsent(page: Page): Promise<void> {
  const body = await page.locator("body").innerText();
  expect(body).not.toMatch(/\bDefinitions\b|\bRevision\b|\bSave\b|\bRefresh\b|\bAdd Alpha\b/);
}

async function attachResponses(testInfo: TestInfo, responses: string[]): Promise<void> {
  await testInfo.attach("api-responses.txt", {
    body: Buffer.from(`${responses.join("\n")}\n`, "utf8"),
    contentType: "text/plain",
  });
}
