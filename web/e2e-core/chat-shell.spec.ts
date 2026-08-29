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
  const sendBox = await page.getByRole("button", { name: "Send message" }).boundingBox();
  expect(sendBox?.width).toBeGreaterThanOrEqual(44);
  expect(sendBox?.height).toBeGreaterThanOrEqual(44);
  await page.keyboard.press("Escape");
  await expect(open).toBeFocused();
  await expect(open).toHaveAttribute("aria-expanded", "false");
  await expect(sidebar).toHaveAttribute("inert", "");
  await expect(page.locator(".chat-shell")).not.toHaveClass(/chat-shell-navigation-open/);
});

test("Chat exposes an accessible 16 KiB text boundary before execution", async ({ page }) => {
  await page.goto("/chat");
  const message = page.getByRole("textbox", { name: "Message", exact: true });
  await message.fill("a".repeat(16 * 1024 + 1));

  await expect(message).toHaveAttribute("aria-invalid", "true");
  await expect(page.getByRole("alert")).toHaveText("Message exceeds the 16 KiB limit.");
  await expect(page.getByRole("button", { name: "Send message" })).toBeDisabled();
  expect(new URL(page.url()).searchParams.get("session")).toBeNull();
});

test("an unknown durable Session URL fails closed instead of becoming a new Chat", async ({ page }) => {
  const unknownSession = "00000000-0000-4000-8000-000000000999";
  await page.goto(`/chat?session=${unknownSession}`);

  await expect(page.getByRole("alert")).toHaveText(
    "The Research Agent session could not be loaded.",
  );
  await expect(page.getByRole("status")).toHaveText("Agent disconnected");
  await expect(page.getByRole("textbox", { name: "Message", exact: true })).toBeDisabled();
  await expect(page).toHaveURL(new RegExp(`/chat\\?session=${unknownSession}$`));
});

test("first Chat turn streams through Caddy and reload replays without another run", async ({ page }) => {
  const runRequests: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.endsWith("/agent/research/run")) {
      runRequests.push(request.url());
    }
  });

  await page.goto("/chat");
  const message = page.getByRole("textbox", { name: "Message", exact: true });
  await expect(message).toBeEnabled();
  expect(new URL(page.url()).searchParams.get("session")).toBeNull();
  await page.getByLabel("Model", { exact: true }).selectOption(
    "scripted-deep-research",
  );
  await expect(page.getByLabel("Reasoning", { exact: true })).toHaveValue("high");

  const responsePromise = page.waitForResponse((response) =>
    new URL(response.url()).pathname.endsWith("/agent/research/run"),
  ).then((response) => ({
    headers: response.headers(),
    status: response.status(),
  }));
  await message.fill("Build a low volatility Alpha.");
  await page.getByRole("button", { name: "Send message" }).click();

  await expect.poll(() => new URL(page.url()).searchParams.get("session")).toMatch(
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
  );
  await expect(page.locator(".chat-message-user .chat-message-content")).toHaveText(
    "Build a low volatility Alpha.",
  );
  await expect(page.locator(".chat-message-assistant .chat-message-content")).toHaveText(
    "I can help turn that idea into a testable Alpha.",
  );
  await expect(page.getByRole("status")).toHaveText("Run complete");

  const response = await responsePromise;
  expect(response.status).toBe(200);
  expect(response.headers["content-type"]).toContain("text/event-stream");
  expect(runRequests).toHaveLength(1);

  const durableUrl = page.url();
  await page.reload();
  await expect(page).toHaveURL(durableUrl);
  await expect(page.getByRole("status")).toHaveText("Ready");
  await expect(page.getByLabel("Model", { exact: true })).toHaveValue(
    "scripted-deep-research",
  );
  await expect(page.getByLabel("Reasoning", { exact: true })).toHaveValue("high");
  await expect(page.getByRole("article")).toHaveCount(2);
  await expect(page.locator(".chat-message-user .chat-message-content")).toHaveText(
    "Build a low volatility Alpha.",
  );
  await expect(page.locator(".chat-message-assistant .chat-message-content")).toHaveText(
    "I can help turn that idea into a testable Alpha.",
  );
  expect(runRequests).toHaveLength(1);
});
