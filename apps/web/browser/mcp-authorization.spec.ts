import { expect, test } from "./workbench-fixture";

test("MCP approval finishes when callback navigation leaves the authorization document open", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.route("**/api/auth/mcp/authorization", route => route.fulfill({
    json: { name: "Codex", scopes: ["research:read", "offline_access"] },
  }));
  await page.route("**/api/auth/oauth2/consent", route => route.fulfill({
    json: { redirect: true, url: "http://127.0.0.1:8765/callback?code=fixture-code&state=fixture-state" },
  }));
  // A browser that cancels the handoff retains the actual product document.
  await page.addInitScript(() => window.addEventListener("beforeunload", event => {
    event.preventDefault(); event.returnValue = "";
  }));
  await page.goto("/connections/mcp/authorize?client_id=fixture-client&state=fixture-state");
  await expect(page.getByRole("heading", { name: "Allow Codex to access QAgentis?" })).toBeVisible();
  let retainedDocument = false;
  page.once("dialog", async dialog => {
    retainedDocument = dialog.type() === "beforeunload";
    await dialog.dismiss();
  });
  await page.getByRole("button", { name: "Allow access", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Access approved", exact: true })).toBeVisible();
  expect(retainedDocument).toBe(true);
  await expect(page.getByRole("status")).toContainText("Return to Codex. You can close this page.");
  await expect(page.getByRole("button", { name: "Allow access", exact: true })).toHaveCount(0);
  await expect(page.getByText("Continuing…", { exact: true })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("mcp-approved-retained-page.png") });
});
