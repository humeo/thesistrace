import { expect, test } from "@playwright/test";
import { buildProductFixture } from "./build-product-fixture";
let fixture: Awaited<ReturnType<typeof buildProductFixture>>;
test.beforeAll(async () => { fixture = await buildProductFixture(new URL("./fixtures/mcp.tsx", import.meta.url), "McpFixture"); });
for (const width of [320, 390, 768, 1280, 1440]) {
  test(`MCP nested instructions, copy feedback and revoke recovery at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    let revokeFailure = true;
    let revokeCalls = 0;
    await page.route("http://mcp.test/**", route => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
      if (path.endsWith("/connections")) return route.fulfill({ json: { server_url: "https://quantgrove.example.test/mcp", apps: [{ id: "00000000-0000-4000-8000-000000000001", client_id: "client-1", name: "Research assistant", scopes: ["research:read"], authorized_at: "2026-09-26T00:00:00Z" }] } });
      if (path.endsWith("/connection")) return route.fulfill({ json: { checked_at: "2026-09-26T00:00:00Z", tools: [{ name: "get_research_context", description: "Live tool" }] } });
      if (!path.endsWith("/revoke")) return route.fulfill({ status: 404 });
      revokeCalls += 1;
      return route.fulfill({ status: revokeFailure ? 503 : 204 });
    });
    await page.addInitScript(() => Object.defineProperty(navigator, "clipboard", { value: { writeText: async () => { throw Error("clipboard denied"); } }, configurable: true }));
    await page.goto("http://mcp.test/");
    await page.addStyleTag({ content: fixture.styles });
    await page.addScriptTag({ content: fixture.script });
    await expect(page.getByText("Service available", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Copy setup prompt" }).click();
    await expect(page.locator('[data-slot="toast-title"]')).toContainText("Copy failed");
    await page.locator('[data-slot="toast-close"]').click();
    const group = page.getByRole("button", { name: "Research preparation 1 tool" });
    await group.click();
    const tool = page.getByRole("button", { name: /Check research readiness/ });
    await tool.click();
    await expect(page.getByText("get_research_context", { exact: true })).toBeVisible();
    const revoke = page.getByRole("button", { name: "Revoke access for Research assistant" });
    await revoke.click();
    const dialog = page.getByRole("alertdialog");
    await expect(dialog.getByRole("button", { name: "Cancel", exact: true })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(revoke).toBeFocused();
    expect(revokeCalls).toBe(0);
    await revoke.click();
    await dialog.getByRole("button", { name: "Revoke access", exact: true }).click();
    await expect(dialog.getByRole("alert")).toContainText("could not be revoked");
    await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
    await page.getByRole("button", { name: "简体中文" }).click();
    await expect(tool).toHaveCount(0);
    await expect(page.getByText("get_research_context", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.getByRole("button", { name: "English", exact: true }).click();
    revokeFailure = false;
    await revoke.click();
    await dialog.getByRole("button", { name: "Revoke access", exact: true }).click();
    await expect(page.getByText("No authorized apps yet")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Authorized apps" })).toBeFocused();
  });
}

test("long authorization target stays readable and successful revoke focuses a stable heading during service check", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 900 });
  const appName = "ResearchAssistant".repeat(8);
  await page.route("http://mcp.test/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    if (path.endsWith("/connections")) return route.fulfill({ json: { server_url: "https://quantgrove.example.test/mcp", apps: [{ id: "00000000-0000-4000-8000-000000000001", client_id: "client-1", name: appName, scopes: ["research:read"], authorized_at: "2026-09-26T00:00:00Z" }] } });
    if (path.endsWith("/connection")) return; // A pending service probe must not block app management.
    return route.fulfill({ status: path.endsWith("/revoke") ? 204 : 404 });
  });
  await page.goto("http://mcp.test/");
  await page.addStyleTag({ content: fixture.styles });
  await page.addScriptTag({ content: fixture.script });
  const title = page.getByRole("article", { name: appName }).locator('[data-slot="card-title"]');
  await expect(title).toBeVisible();
  expect.soft(await title.evaluate(el => el.scrollWidth <= el.clientWidth && el.getBoundingClientRect().right <= el.closest('[data-slot="card"]')!.getBoundingClientRect().right)).toBe(true);
  await page.getByRole("button", { name: `Revoke access for ${appName}` }).click();
  const dialog = page.getByRole("alertdialog");
  const dialogTitle = dialog.locator('[data-slot="alert-dialog-title"]');
  expect.soft(await dialogTitle.evaluate(el => el.scrollWidth <= el.clientWidth && el.getBoundingClientRect().right <= el.closest('[role="alertdialog"]')!.getBoundingClientRect().right)).toBe(true);
  await dialog.getByRole("button", { name: "Revoke access", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Authorized apps" })).toBeFocused();
});
