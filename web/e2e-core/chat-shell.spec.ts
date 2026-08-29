import { createResearcher, expect, securityTest, test } from "./auth-fixture";

securityTest("Chat preserves returnTo and opens after login without a document reload", async ({ page }) => {
  const email = "browser-chat-return@example.test";
  await createResearcher(page, email);
  await page.context().clearCookies();

  await page.goto("/chat");
  await expect(page).toHaveURL(/\/login\?returnTo=/);
  expect(new URL(page.url()).searchParams.get("returnTo")).toBe("/chat");

  const documentRequests: string[] = [];
  page.on("request", (request) => {
    if (request.resourceType() === "document") documentRequests.push(request.url());
  });
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("Browser-acceptance-password-2026");
  documentRequests.length = 0;
  await page.getByRole("button", { name: "Log in" }).click();

  await expect(page).toHaveURL(/\/chat$/);
  await expect(
    page.getByRole("heading", { name: "Turn an investment idea into Alpha" }),
  ).toBeVisible();
  expect(documentRequests).toEqual([]);
});

test("Chat exposes the registered Catalog and responsive Session sidebar through Caddy", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/chat");

  await expect(
    page.getByRole("heading", { name: "Turn an investment idea into Alpha" }),
  ).toBeVisible();
  const model = page.getByLabel("Model", { exact: true });
  const reasoning = page.getByLabel("Reasoning", { exact: true });
  await expect(model).toHaveValue("scripted-research");
  await expect(reasoning).toHaveValue("medium");
  await expect(reasoning.locator("option")).toHaveText(["Low", "Medium", "High"]);

  await model.selectOption("scripted-deep-research");
  await expect(reasoning).toHaveValue("high");
  await expect(reasoning.locator("option")).toHaveText(["High"]);

  const sidebar = page.locator("#chat-navigation");
  await expect(sidebar.getByRole("link", { name: "ThesisTrace home" })).toBeVisible();
  await expect(sidebar.getByRole("link", { name: "New Chat" })).toBeVisible();
  await expect(sidebar.getByRole("navigation", { name: "Workspace" })).toBeVisible();
  await expect(sidebar.getByRole("heading", { name: "Chats" })).toBeVisible();
  await expect(sidebar.getByLabel("Account menu")).toBeVisible();

  const collapse = page.getByRole("button", { name: "Collapse sidebar" });
  await collapse.click();
  await expect(page.locator(".chat-shell")).toHaveClass(/chat-shell-collapsed/);
  await expect(page.getByRole("button", { name: "Expand sidebar" })).toHaveAttribute(
    "aria-expanded",
    "false",
  );
  await expect.poll(
    () => sidebar.evaluate((element) => element.getBoundingClientRect().width),
  ).toBe(56);

  await page.setViewportSize({ width: 390, height: 844 });
  const open = page.getByRole("button", { name: "Open navigation" });
  await expect(sidebar).toHaveAttribute("inert", "");
  await open.click();
  await expect(open).toHaveAttribute("aria-expanded", "true");
  await expect(sidebar).not.toHaveAttribute("inert", "");
  await expect(page.locator(".chat-shell")).toHaveClass(/chat-shell-navigation-open/);
  await expect.poll(
    () => sidebar.evaluate((element) => element.getBoundingClientRect().left),
  ).toBe(0);

  const close = sidebar.getByRole("button", { name: "Close navigation" });
  await expect(close).toBeFocused();
  const closeBox = await close.boundingBox();
  expect(closeBox?.width).toBeGreaterThanOrEqual(44);
  expect(closeBox?.height).toBeGreaterThanOrEqual(44);
  await page.keyboard.press("Escape");
  await expect(open).toBeFocused();
  await expect(open).toHaveAttribute("aria-expanded", "false");
  await expect(sidebar).toHaveAttribute("inert", "");
  await expect(page.locator(".chat-shell")).not.toHaveClass(/chat-shell-navigation-open/);
});
