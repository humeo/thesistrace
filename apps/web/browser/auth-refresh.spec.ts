import { expect, test } from "./workbench-fixture";

test("a temporary Auth refresh failure preserves the blocked workspace and restores its editor", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  let status = 200;
  let reads = 0;
  await page.route("**/api/auth/get-session", route => {
    reads += 1;
    return status === 200 ? route.fulfill({ json: {
      session: { id: "00000000-0000-4000-8000-000000000002" },
      user: { id: "00000000-0000-4000-8000-000000000001", email: "browser@example.test", name: "Browser", active: true },
    } }) : route.fulfill({ status, json: { message: "Temporarily unavailable" } });
  });
  await page.goto("/research");
  await page.getByRole("button", { name: "Strategy Backtest", exact: true }).click();
  const notes = page.getByRole("textbox", { name: "Research notes (optional)", exact: true });
  await notes.fill("Unsent local editor state");
  const original = await notes.elementHandle();
  await page.getByRole("button", { name: "Account menu", exact: true }).click();
  await expect(page.getByRole("button", { name: "Log out", exact: true })).toBeVisible();
  const before = reads;
  status = 503;
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect.poll(() => reads).toBeGreaterThan(before);
  await expect(page.getByRole("heading", { name: "Authentication unavailable", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Log out", exact: true })).toHaveCount(0);
  expect(await original!.evaluate(element => element.isConnected)).toBe(true);
  await expect(page.getByRole("textbox", { name: "Research notes (optional)", exact: true })).toHaveCount(0);
  const blocked = page.getByRole("dialog", { name: "Authentication unavailable", exact: true });
  await page.keyboard.press("Escape");
  await expect(blocked).toBeVisible();
  status = 200;
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(notes).toHaveValue("Unsent local editor state");
  expect(await original!.evaluate(element => element.isConnected)).toBe(true);
  status = 401;
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page).toHaveURL(/\/login/);
  expect(await original!.evaluate(element => element.isConnected)).toBe(false);
});
