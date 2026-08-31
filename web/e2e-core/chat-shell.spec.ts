import { execFileSync, spawnSync, type ChildProcess } from "node:child_process";
import type { Locator, Page, Route } from "@playwright/test";

import {
  createResearcher,
  expect,
  restoreResearcherSession,
  sameOriginHeaders,
  securityTest,
  test,
  testProjectName,
} from "./auth-fixture";
import { proxyState, setProxyMode } from "./fault-proxy";
import {
  controlledWorkerExit,
  controlWorker,
  startControlledResearchRun,
} from "./research-run-control";

const scriptedFactorIdeaPrompt =
  "Evaluate a low-volatility Alpha idea as a Factor Evaluation using reliable ThesisTrace defaults.";
const scriptedFactorSubmitOnlyPrompt =
  "Submit a low-volatility Factor Evaluation and return as soon as ThesisTrace accepts it.";
const scriptedResumeResearchPrompt =
  "Resume the accepted ResearchRun from this Chat and explain its authoritative Result when available.";
const scriptedStrategyPrompt =
  "Backtest a low-volatility Alpha strategy using reliable ThesisTrace defaults.";
const scriptedLargeA2UITablePrompt =
  "[scripted-a2ui-table] Show a large renderer acceptance sample, not research evidence.";

function agentRunStatus(page: Page) {
  return page.locator(".chat-composer-status-row").getByRole("status");
}

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
  await expect(page.getByText("No conversations yet", { exact: true })).toBeVisible();
  await collapse.click();
  await expect(page.locator(".chat-shell")).toHaveClass(/chat-shell-collapsed/);
  await expect(sidebar.getByText("Empty", { exact: true })).toBeVisible();
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

  await expect(page.getByRole("heading", { name: "Chat not found" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Start a New Chat" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Message", exact: true })).toHaveCount(0);
  await expect(page).toHaveURL(new RegExp(`/chat\\?session=${unknownSession}$`));

  await page.goto(`/chat?session=${unknownSession}&session=${unknownSession}`);
  await expect(page.getByRole("heading", { name: "Chat not found" })).toBeVisible();
  await expect(page).toHaveURL(/\/chat\?session=.*&session=.*/);
});

test("first Chat turn streams through Caddy and reload replays without another run", async ({ page }) => {
  const runRequests: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.endsWith("/agent/research/run")) {
      runRequests.push(request.url());
    }
  });

  await page.goto("/chat");
  const message = page.getByRole("textbox", { name: "Message", exact: true });
  await expect(message).toBeEnabled();
  await expect(page.getByText("No conversations yet", { exact: true })).toBeVisible();
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
  const assistant = page.locator(".chat-message-assistant .chat-message-content");
  await expect(assistant).toBeVisible();
  const assistantText = await assistant.textContent();
  if (assistantText === null) throw new Error("Expected one assistant response");
  expect(assistantText.trim().length).toBeGreaterThan(0);
  expect(new TextEncoder().encode(assistantText).byteLength).toBeLessThanOrEqual(512);
  await expect(agentRunStatus(page)).toHaveText("Run complete");
  const generatedTitleElement = page.locator(".chat-session-title strong");
  await expect.poll(async () => {
    const value = (await generatedTitleElement.textContent())?.trim();
    return value !== undefined
      && !["", "New Chat", "Loading Chat", "Untitled"].includes(value)
      ? value
      : null;
  }).not.toBeNull();
  const generatedTitle = (await generatedTitleElement.textContent())?.trim();
  if (generatedTitle === undefined || generatedTitle.length === 0) {
    throw new Error("Accepted Chat exposed no generated title");
  }
  expect([...generatedTitle].length).toBeLessThanOrEqual(80);
  await expect(page.getByRole("heading", { name: "Today" })).toBeVisible();
  const generatedSessionLink = page.getByRole("link", { name: generatedTitle, exact: true });
  await expect(generatedSessionLink).toHaveAttribute("aria-current", "page");
  const durableUrl = page.url();
  const durableSession = new URL(durableUrl).searchParams.get("session");
  if (durableSession === null) throw new Error("Accepted Chat exposed no durable Session id");
  setAgentSessionTitle(durableSession, "Untitled");
  await page.reload();
  await expect(page.locator(".chat-session-title strong")).toHaveText("Untitled");
  await expect(agentRunStatus(page)).toHaveText("Run complete");
  const failedDelete = async (route: Route) => {
    if (route.request().method() !== "DELETE") {
      await route.continue();
      return;
    }
    await route.fulfill({
      body: JSON.stringify({ code: "AGENT_SERVICE_UNAVAILABLE" }),
      contentType: "application/json",
      status: 503,
    });
  };
  await page.route("**/api/agent/sessions/*", failedDelete);
  await page.getByRole("button", { name: "Actions for Untitled" }).click();
  await page.getByRole("menuitem", { name: "Delete Chat" }).click();
  const failedDeleteDialog = page.getByRole("dialog", { name: "Delete Chat?" });
  await failedDeleteDialog.getByRole("button", { name: "Delete Chat" }).click();
  await expect(failedDeleteDialog.getByRole("alert")).toHaveText(
    "The Chat could not be deleted.",
  );
  await page.unroute("**/api/agent/sessions/*", failedDelete);
  await failedDeleteDialog.getByRole("button", { name: "Close dialog" }).click();
  await expect(failedDeleteDialog).toHaveCount(0);
  const recoveredTitle = "Recovered Chat title";
  const transitioningActions = page.getByRole("button", { name: "Actions for Untitled" });
  await transitioningActions.click();
  const transitioningDelete = page.getByRole("menuitem", { name: "Delete Chat" });
  await page.keyboard.press("Tab");
  await expect(transitioningDelete).toBeFocused();
  setAgentSessionActiveRun(durableSession, true);
  try {
    setAgentSessionTitle(durableSession, recoveredTitle);
    await expect(page.getByRole("menu", { name: "Actions for Untitled" })).toHaveCount(0);
    await expect(page.getByRole("button", {
      name: `Actions for ${recoveredTitle}`,
    })).toBeFocused();
    await expect(page.getByRole("link", {
      exact: true,
      name: `${recoveredTitle}, Running`,
    })).toHaveAttribute("aria-current", "page");
  } finally {
    setAgentSessionActiveRun(durableSession, false);
  }
  await expect(page.locator(".chat-session-title strong")).toHaveText(recoveredTitle);
  seedActiveAgentLayoutSession(durableSession);
  await page.reload();
  const activeLayoutRow = page.locator(".chat-session-row").filter({
    hasText: "Active layout session",
  });
  await expect(activeLayoutRow).toBeVisible();
  await page.getByRole("button", { name: "Collapse sidebar" }).click();
  const activeLayoutIconBounds = await activeLayoutRow.locator("a svg").boundingBox();
  const activeLayoutStatus = activeLayoutRow.locator(".chat-session-run-compact");
  await expect(activeLayoutStatus).toHaveText("Run");
  await expect(activeLayoutStatus).toHaveCSS("font-size", "12px");
  await expect(activeLayoutRow.getByRole("link", {
    exact: true,
    name: "Active layout session, Running",
  })).toBeVisible();
  const currentIndicator = await page.locator(".chat-session-row-current").evaluate((element) => {
    const style = window.getComputedStyle(element, "::before");
    return { backgroundColor: style.backgroundColor, width: style.width };
  });
  expect(currentIndicator.width).toBe("2px");
  expect(currentIndicator.backgroundColor).not.toBe("rgba(0, 0, 0, 0)");
  const activeLayoutStatusBounds = await activeLayoutStatus.boundingBox();
  if (activeLayoutIconBounds === null || activeLayoutStatusBounds === null) {
    throw new Error("Collapsed active Session did not expose measurable icon and status");
  }
  expect(activeLayoutIconBounds.y + activeLayoutIconBounds.height)
    .toBeLessThanOrEqual(activeLayoutStatusBounds.y);
  const collapsedActions = page.getByRole("button", { name: `Actions for ${recoveredTitle}` });
  await expect(collapsedActions).toBeVisible();
  const collapsedActionTarget = await collapsedActions.boundingBox();
  expect(collapsedActionTarget?.width).toBeGreaterThanOrEqual(36);
  expect(collapsedActionTarget?.height).toBeGreaterThanOrEqual(36);
  await collapsedActions.click();
  const collapsedRenameMenuItem = page.getByRole("menuitem", { name: "Rename" });
  await expect(collapsedRenameMenuItem).toBeVisible();
  await expect(collapsedRenameMenuItem).toBeFocused();
  const collapsedMenu = page.getByRole("menu", { name: `Actions for ${recoveredTitle}` });
  const collapsedMenuBounds = await collapsedMenu.boundingBox();
  const viewport = page.viewportSize();
  expect(collapsedMenuBounds?.width).toBeGreaterThanOrEqual(150);
  expect(collapsedMenuBounds?.x).toBeGreaterThanOrEqual(0);
  expect((collapsedMenuBounds?.x ?? 0) + (collapsedMenuBounds?.width ?? 0))
    .toBeLessThanOrEqual(viewport?.width ?? 0);
  await page.keyboard.press("Escape");
  await expect(collapsedActions).toBeFocused();
  await page.getByRole("button", { name: "Expand sidebar" }).click();
  removeActiveAgentLayoutSession();
  await page.reload();

  const response = await responsePromise;
  expect(response.status).toBe(200);
  expect(response.headers["content-type"]).toContain("text/event-stream");
  expect(runRequests).toHaveLength(1);

  const sessionActions = page.getByRole("button", { name: `Actions for ${recoveredTitle}` });
  await sessionActions.click();
  const renameMenuItem = page.getByRole("menuitem", { name: "Rename" });
  const deleteMenuItem = page.getByRole("menuitem", { name: "Delete Chat" });
  await expect(renameMenuItem).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(deleteMenuItem).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(renameMenuItem).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(deleteMenuItem).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(sessionActions).toBeFocused();
  await sessionActions.click();
  await expect(renameMenuItem).toBeFocused();
  await page.evaluate(() => window.dispatchEvent(new Event("resize")));
  await expect(page.getByRole("menu", { name: `Actions for ${recoveredTitle}` })).toHaveCount(0);
  await expect(sessionActions).toBeFocused();
  await sessionActions.click();
  await page.getByRole("menuitem", { name: "Rename" }).click();
  const renameDialog = page.getByRole("dialog", { name: "Rename Chat" });
  await expect(renameDialog.getByLabel("Title")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(renameDialog).toHaveCount(0);
  await expect(sessionActions).toBeFocused();
  await sessionActions.click();
  await page.getByRole("menuitem", { name: "Rename" }).click();
  const renamedTitle = "😀".repeat(80);
  await renameDialog.getByLabel("Title").fill("Untitled");
  await renameDialog.getByRole("button", { name: "Save title" }).click();
  await expect(renameDialog.getByRole("alert")).toHaveText(
    "Choose a title between 1 and 80 characters other than Untitled.",
  );

  const malformedRename = async (route: Route) => {
    if (route.request().method() !== "PATCH") {
      await route.continue();
      return;
    }
    await route.fulfill({
      body: JSON.stringify({
        id: durableSession,
        title: "Malformed response",
        version: "2026-08-30T04:00:01.000Z",
      }),
      contentType: "application/json",
      status: 200,
    });
  };
  await page.route("**/api/agent/sessions/*", malformedRename);
  await renameDialog.getByLabel("Title").fill("Valid local title");
  await renameDialog.getByRole("button", { name: "Save title" }).click();
  await expect(renameDialog.getByRole("alert")).toHaveText(
    "The Chat title response was invalid.",
  );
  await page.unroute("**/api/agent/sessions/*", malformedRename);

  await renameDialog.getByLabel("Title").fill(renamedTitle);
  await renameDialog.getByRole("button", { name: "Save title" }).click();
  await expect(renameDialog).toHaveCount(0);
  await expect(page.locator(".chat-session-title strong")).toHaveText(renamedTitle);
  await expect(page.getByRole("link", { name: renamedTitle, exact: true })).toHaveAttribute(
    "aria-current",
    "page",
  );

  await page.getByRole("link", { name: "New Chat", exact: true }).click();
  await expect(page).toHaveURL(/\/chat$/);
  await expect(
    page.getByRole("heading", { name: "Turn an investment idea into Alpha" }),
  ).toBeVisible();
  await page.getByRole("textbox", { name: "Message", exact: true }).fill(
    "This unsent draft belongs only to the ephemeral Chat.",
  );
  await page.goBack();
  await expect(page).toHaveURL(durableUrl);
  await expect(page.getByText("Build a low volatility Alpha.", { exact: true })).toBeVisible();
  await expect(page.locator(".chat-session-title strong")).toHaveText(renamedTitle);
  await expect(page.getByRole("textbox", { name: "Message", exact: true })).toHaveValue("");
  await page.goForward();
  await expect(page).toHaveURL(/\/chat$/);
  await expect(page.getByRole("textbox", { name: "Message", exact: true })).toHaveValue("");
  await page.getByRole("link", { name: renamedTitle, exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/chat\\?session=${durableSession}$`));

  await page.reload();
  await expect(page).toHaveURL(durableUrl);
  await expect(agentRunStatus(page)).toHaveText("Run complete");
  await expect(page.getByLabel("Model", { exact: true })).toHaveValue(
    "scripted-deep-research",
  );
  await expect(page.getByLabel("Reasoning", { exact: true })).toHaveValue("high");
  await expect(page.getByRole("article")).toHaveCount(2);
  await expect(page.locator(".chat-message-user .chat-message-content")).toHaveText(
    "Build a low volatility Alpha.",
  );
  await expect(page.locator(".chat-message-assistant .chat-message-content")).toHaveText(
    assistantText,
  );
  await expect(page.locator(".chat-session-title strong")).toHaveText(renamedTitle);
  expect(runRequests).toHaveLength(1);

  await page.setViewportSize({ height: 844, width: 390 });
  const openNavigation = page.getByRole("button", { name: "Open navigation" });
  await openNavigation.click();
  const mobileActions = page.getByRole("button", { name: `Actions for ${renamedTitle}` });
  const mobileSessionLink = page.getByRole("link", { name: renamedTitle, exact: true });
  for (const target of [mobileActions, mobileSessionLink]) {
    const bounds = await target.boundingBox();
    expect(bounds?.width).toBeGreaterThanOrEqual(44);
    expect(bounds?.height).toBeGreaterThanOrEqual(44);
  }
  await mobileActions.click();
  await expect(page.getByRole("menu", { name: `Actions for ${renamedTitle}` })).toBeVisible();
  const navigationBackdrop = page.locator(".chat-navigation-backdrop");
  const navigationBackdropBounds = await navigationBackdrop.boundingBox();
  if (navigationBackdropBounds === null) {
    throw new Error("Mobile navigation exposed no clickable backdrop");
  }
  await navigationBackdrop.click({
    position: {
      x: navigationBackdropBounds.width - 8,
      y: navigationBackdropBounds.height / 2,
    },
  });
  await expect(page.getByRole("menu", { name: `Actions for ${renamedTitle}` })).toHaveCount(0);
  await expect(page.locator("#chat-navigation")).toHaveAttribute("inert", "");
  await expect(openNavigation).toBeFocused();
  await openNavigation.click();
  await mobileActions.click();
  await page.keyboard.press("Escape");
  await expect(page.locator(".chat-shell")).toHaveClass(/chat-shell-navigation-open/);
  await expect(mobileActions).toBeFocused();
  await mobileActions.click();
  await page.getByRole("menuitem", { name: "Rename" }).click();
  await page.keyboard.press("Escape");
  await expect(page.locator(".chat-shell")).toHaveClass(/chat-shell-navigation-open/);
  await expect(mobileActions).toBeFocused();
  await mobileActions.click();
  await expect(page.getByRole("menu", { name: `Actions for ${renamedTitle}` })).toBeVisible();
  expect((await page.request.delete(`/api/agent/sessions/${durableSession}`, {
    headers: sameOriginHeaders(),
  })).status()).toBe(204);
  await page.evaluate(async () => {
    const input = document.querySelector<HTMLTextAreaElement>(
      'textarea[aria-label="Message"]',
    );
    const form = input?.closest("form");
    const valueSetter = Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    )?.set;
    if (
      !(input instanceof HTMLTextAreaElement)
      || !(form instanceof HTMLFormElement)
      || valueSetter === undefined
    ) {
      throw new Error("Chat composer is unavailable");
    }
    valueSetter.call(input, "Refresh the deleted Session state.");
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
    form.requestSubmit();
  });
  await expect(page.getByRole("menu", { name: `Actions for ${renamedTitle}` })).toHaveCount(0);
  await expect(page.getByText("No conversations yet", { exact: true })).toBeVisible();
  await expect(page.locator(".chat-shell")).toHaveClass(/chat-shell-navigation-open/);
  await expect(page.getByRole("link", { name: "New Chat", exact: true })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.locator(".chat-shell")).not.toHaveClass(/chat-shell-navigation-open/);
  await expect(openNavigation).toBeFocused();
});

test("Chat executes a real protected MCP read Tool and renders only its safe lifecycle", async ({ page }) => {
  const runResponse = page.waitForResponse((response) =>
    new URL(response.url()).pathname.endsWith("/agent/research/run"),
  );
  await page.goto("/chat");
  const prompt = "[scripted-tool-turn] Inspect the available research context.";
  await page.getByRole("textbox", { name: "Message", exact: true }).fill(prompt);
  await page.getByRole("button", { name: "Send message" }).click();

  const tool = page.getByRole("article", {
    name: "Tool get_research_context: Completed",
  });
  await expect(tool).toBeVisible();
  await expect(tool).toContainText("MCP Tool");
  await expect(tool).toContainText("get_research_context");
  await expect(tool).toContainText("Completed");
  await expect(tool.locator(".chat-tool-duration")).toHaveText(/^(?:\d+ ms|\d+\.\d+ s)$/);
  await expect(agentRunStatus(page)).toHaveText("Run complete");
  const assistant = page.locator(".chat-message-assistant .chat-message-content");
  await expect(assistant).toBeVisible();
  const assistantText = await assistant.textContent();
  if (assistantText === null) throw new Error("Expected one assistant explanation");
  expect(assistantText.trim().length).toBeGreaterThan(0);
  expect(new TextEncoder().encode(assistantText).byteLength).toBeLessThanOrEqual(512);

  const response = await runResponse;
  expect(response.status()).toBe(200);
  await page.setViewportSize({ width: 320, height: 720 });
  await expect(page.locator("#chat-navigation")).toHaveCSS("visibility", "hidden");
  const compactToolLayout = await tool.evaluate((element) => {
    const toolBounds = element.getBoundingClientRect();
    const fieldBounds = [
      ".chat-tool-kind",
      "code",
      ".chat-tool-status",
      ".chat-tool-duration",
    ].map((selector) => {
      const field = element.querySelector(selector);
      if (!(field instanceof HTMLElement)) throw new Error(`Missing ${selector}`);
      return field.getBoundingClientRect();
    });
    return {
      allFieldsInside: fieldBounds.every((bounds) =>
        bounds.left >= toolBounds.left - 1
        && bounds.right <= toolBounds.right + 1
        && bounds.top >= toolBounds.top - 1
        && bounds.bottom <= toolBounds.bottom + 1
      ),
      rows: new Set(fieldBounds.map((bounds) => (
        Math.round((bounds.top + bounds.bottom) / 2)
      ))).size,
      toolOverflow: element.scrollWidth > element.clientWidth,
      viewportOverflow:
        document.documentElement.scrollWidth > document.documentElement.clientWidth,
    };
  });
  expect(compactToolLayout).toEqual({
    allFieldsInside: true,
    rows: 2,
    toolOverflow: false,
    viewportOverflow: false,
  });
  await expect(page.locator("body")).not.toContainText("data_overview");
  await expect(page.locator("body")).not.toContainText("authoring_constraints");

  const durableUrl = page.url();
  await page.reload();
  await expect(page).toHaveURL(durableUrl);
  const replayedTool = page.getByRole("article", {
    name: "Tool get_research_context: Completed",
  });
  await expect(replayedTool).toContainText("Duration unavailable");
  await expect(page.locator(".chat-message-assistant .chat-message-content")).toHaveText(
    assistantText,
  );
  await expect(page.locator("body")).not.toContainText("Tool completed.");
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("link", { name: "New Chat", exact: true }).click();
  await expect(page.getByRole("article", {
    name: "Tool get_research_context: Completed",
  })).toHaveCount(0);
  await expect(page.getByRole("textbox", { name: "Message", exact: true })).toHaveValue("");
});

for (const [scenario, prompt] of [
  ["component action", "[scripted-invalid-a2ui] Attempt one unsafe research surface."],
  ["top-level field", "[scripted-invalid-a2ui-top-level] Attempt an unknown top-level render field."],
  ["non-empty data", "[scripted-invalid-a2ui-data] Attempt non-empty render data."],
] as const) {
test(`Chat rejects an invalid model-authored A2UI surface and remains usable: ${scenario}`, async ({ page }) => {
  await page.goto("/chat");
  await page.evaluate(() => {
    const evidence = { sawUnsafeSurface: false };
    Object.assign(window, { a2uiRejectionEvidence: evidence });
    new MutationObserver(() => {
      evidence.sawUnsafeSurface ||= document.body.textContent
        ?.includes("MALICIOUS_A2UI_SHOULD_NOT_RENDER") === true;
    }).observe(document.body, { characterData: true, childList: true, subtree: true });
  });
  const message = page.getByRole("textbox", { name: "Message", exact: true });
  await message.fill(prompt);
  await page.getByRole("button", { name: "Send message" }).click();

  await expect(agentRunStatus(page)).toHaveText("Run complete");
  expect(await page.evaluate(() => (
    window as Window & { a2uiRejectionEvidence?: { sawUnsafeSurface: boolean } }
  ).a2uiRejectionEvidence?.sawUnsafeSurface)).toBe(false);
  const safeError = page.getByRole("alert").filter({
    hasText: "This research surface could not be displayed.",
  });
  await expect(safeError).toHaveText(
    "This research surface could not be displayed. The conversation is still available.",
  );
  await expect(page.locator("body")).not.toContainText("MALICIOUS_A2UI_SHOULD_NOT_RENDER");
  await expect(page.locator("body")).not.toContainText("delete_research");
  await expect(page.getByRole("article", { name: /Tool render_a2ui:/ })).toHaveCount(0);
  await expect(page.locator(".chat-message-assistant .chat-message-content").last())
    .toContainText("unsafe research surface was rejected");
  await expect(message).toBeEnabled();

  const durableUrl = page.url();
  const sessionId = new URL(durableUrl).searchParams.get("session");
  if (sessionId === null) throw new Error("Rejected A2UI Chat exposed no Session id");
  expect(agentChatDatabaseFacts(sessionId).a2ui).toBe(1);
  await page.reload();
  await expect(page).toHaveURL(durableUrl);
  await expect(safeError).toHaveText(
    "This research surface could not be displayed. The conversation is still available.",
  );
  expect(agentChatDatabaseFacts(sessionId).a2ui).toBe(1);

  const assistantMessages = page.locator(".chat-message-assistant .chat-message-content");
  const assistantCount = await assistantMessages.count();
  const continuationResponse = page.waitForResponse((response) => (
    new URL(response.url()).pathname.endsWith("/agent/research/run")
  ));
  await message.fill("Continue after rejecting that unsafe surface.");
  await page.getByRole("button", { name: "Send message" }).click();
  expect((await continuationResponse).status()).toBe(200);
  await expect(assistantMessages).toHaveCount(assistantCount + 1);
  await expect(agentRunStatus(page)).toHaveText("Run complete");
  await expect(assistantMessages.last())
    .toContainText("testable Alpha");
  await expect(safeError).toBeVisible();
});
}

test("A2UI shows real running state and supports keyboard and narrow-screen result interactions", async ({ page }, testInfo) => {
  test.setTimeout(180_000);
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  let worker: ChildProcess | undefined;
  controlWorker("pause");
  try {
    await page.goto("/chat");
    await page.getByRole("textbox", { name: "Message", exact: true }).fill(scriptedFactorIdeaPrompt);
    await page.getByRole("button", { name: "Send message" }).click();
    const admitted = page.getByRole("article", { name: "Tool submit_research_run: Completed" });
    await expect(admitted).toBeVisible({ timeout: 30_000 });
    const href = await admitted.locator("a.chat-tool-resource").getAttribute("href");
    const runId = href?.split("/").at(-1);
    if (runId === undefined || !/^run_[a-f0-9]{20}$/.test(runId)) {
      throw new Error("Admission did not return a safe ResearchRun route");
    }
    const barrier = startControlledResearchRun(runId);
    worker = barrier.process;
    await barrier.claimed;
    const detailResponse = await page.request.get(`/api/research-runs/${runId}`);
    expect(detailResponse.status()).toBe(200);
    const detail = await detailResponse.json() as {
      input: { formula: string }; progress: { phase: string }; status: string;
    };
    expect(detail.status).toBe("running");
    const running = page.getByRole("region", { name: `ResearchRun ${runId}: running` });
    await expect(running).toContainText(detail.progress.phase, { timeout: 30_000 });
    await expect(running).toContainText(detail.input.formula);
    await testInfo.attach("a2ui-running.png", { body: await running.screenshot(), contentType: "image/png" });
    worker.stdin?.end("1");
    await controlledWorkerExit(worker);
    worker = undefined;
    await expect(agentRunStatus(page)).toHaveText("Run complete", { timeout: 90_000 });
    await expect(page.getByRole("article", { name: "Research surface" })).toHaveCount(4);
    await expect(page.getByRole("region", { name: `ResearchRun ${runId}: succeeded` })).toBeVisible();

    const formula = page.getByRole("region", { name: "Proposed formula" });
    const copy = formula.getByRole("button", { name: "Copy" });
    await keyboardFocus(page, copy);
    await page.keyboard.press("Enter");
    await expect(formula.getByText("Formula copied", { exact: true })).toBeAttached();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(detail.input.formula);

    const result = page.getByRole("article", { name: "Research surface" }).last();
    const collapsedControls = result.locator(".chat-a2ui-column > .chat-a2ui-child")
      .filter({ has: page.locator("button[aria-expanded='false'], .chat-a2ui-navigation") });
    await expect(collapsedControls).toHaveCount(3);
    for (const control of await collapsedControls.all()) {
      expect((await control.boundingBox())?.height).toBeLessThanOrEqual(64);
    }
    const disclosure = result.getByRole("button", { name: "Inspect result metrics" });
    await keyboardFocus(page, disclosure);
    await page.keyboard.press("Space");
    await expect(disclosure).toHaveAttribute("aria-expanded", "true");
    const table = result.getByRole("table", { name: "Authoritative factor metrics" });
    await expect(table.getByRole("columnheader")).toHaveCount(2);
    await page.keyboard.press("Enter");
    await expect(disclosure).toHaveAttribute("aria-expanded", "false");
    await page.keyboard.press("Enter");
    await expect(disclosure).toHaveAttribute("aria-expanded", "true");
    const provenance = result.getByRole("button", { name: "Inspect provenance" });
    await keyboardFocus(page, provenance);
    await page.keyboard.press("Enter");
    await expect(provenance).toHaveAttribute("aria-expanded", "true");

    await page.setViewportSize({ width: 390, height: 844 });
    await expectAccessibleNarrowTable(table, 2);
    const navigation = result.getByRole("link", { name: "Open authoritative ResearchRun" });
    for (const target of [copy, disclosure, provenance, navigation]) {
      const bounds = await target.boundingBox();
      expect(bounds?.width).toBeGreaterThanOrEqual(44);
      expect(bounds?.height).toBeGreaterThanOrEqual(44);
    }
    await table.scrollIntoViewIfNeeded();
    await testInfo.attach("a2ui-result-mobile.png", { body: await page.screenshot(), contentType: "image/png" });
    await keyboardFocus(page, navigation);
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(new RegExp(`/research-runs/${runId}$`));
    await expect(page.locator(".research-run-facts")).toContainText("Status succeeded");
  } finally {
    try {
      if (worker !== undefined) {
        worker.kill("SIGTERM");
        await controlledWorkerExit(worker, true);
      }
    } finally {
      controlWorker("unpause");
    }
  }
});

test("a large A2UI table preserves column meaning and layout on a narrow screen", async ({ page }, testInfo) => {
  await page.goto("/chat");
  await page.getByRole("textbox", { name: "Message", exact: true }).fill(scriptedLargeA2UITablePrompt);
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(agentRunStatus(page)).toHaveText("Run complete");
  const disclosure = page.getByRole("button", { name: "Inspect 100 sample rows" });
  await keyboardFocus(page, disclosure);
  await page.keyboard.press("Enter");
  const table = page.getByRole("table", { name: "Renderer acceptance sample — not research evidence" });
  await expect(table.getByRole("row")).toHaveCount(101);
  await expect(table.getByRole("cell")).toHaveCount(1200);
  await page.setViewportSize({ width: 320, height: 720 });
  await expectAccessibleNarrowTable(table, 12);
  await table.getByRole("cell").last().scrollIntoViewIfNeeded();
  await expect(table.getByRole("cell").last()).toContainText("Sample 100:12");
  await testInfo.attach("a2ui-large-table-mobile.png", { body: await page.screenshot(), contentType: "image/png" });
  await page.reload();
  await expect(agentRunStatus(page)).toHaveText("Run complete");
  await disclosure.click();
  await expect(table.getByRole("cell")).toHaveCount(1200);
  await expectAccessibleNarrowTable(table, 12);
});

async function keyboardFocus(page: Page, target: Locator): Promise<void> {
  for (let tabPresses = 0; tabPresses < 80; tabPresses += 1) {
    await page.keyboard.press("Tab");
    if (await target.evaluate((element) => element === document.activeElement)) break;
  }
  await expect(target).toBeFocused();
  await expect(target).toHaveCSS("outline-style", "solid");
  await expect(target).toHaveCSS("outline-width", "2px");
}

async function expectAccessibleNarrowTable(table: Locator, columns: number): Promise<void> {
  await expect(table.getByRole("columnheader")).toHaveCount(columns);
  expect(await table.evaluate((element) => {
    const cells = Array.from(element.querySelectorAll("td"));
    return {
      fieldsPreserved: cells.every((cell) => {
        const header = document.getElementById(cell.getAttribute("headers") ?? "");
        const label = cell.querySelector<HTMLElement>(".chat-a2ui-cell-label");
        return header?.getAttribute("role") === "columnheader"
          && label?.textContent === header.textContent
          && label.getAttribute("aria-hidden") === "true"
          && getComputedStyle(label).display !== "none";
      }),
      pageOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    };
  })).toEqual({ fieldsPreserved: true, pageOverflow: false });
}

test("admitted Research artifacts and a DailyTrack outlive the Chat that created them", async ({
  page,
  researcher,
}) => {
  test.setTimeout(240_000);
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  let agentRunRequests = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.endsWith("/agent/research/run")) {
      agentRunRequests += 1;
    }
  });
  await page.goto("/chat");
  const message = page.getByRole("textbox", { name: "Message", exact: true });
  await message.fill(scriptedFactorSubmitOnlyPrompt);
  await page.getByRole("button", { name: "Send message" }).click();

  await expect(agentRunStatus(page)).toHaveText("Run complete", { timeout: 30_000 });
  const admission = page.getByRole("article", {
    name: "Tool submit_research_run: Completed",
  });
  await expect(admission).toBeVisible();
  await expect(admission).toContainText("ResearchRun");
  await expect(admission).toContainText("queued");
  const runHref = await admission.locator("a.chat-tool-resource").getAttribute("href");
  if (runHref === null) throw new Error("Admission Tool did not expose its safe Run route");
  const runId = runHref.split("/").at(-1);
  if (runId === undefined || !/^run_[a-f0-9]{20}$/.test(runId)) {
    throw new Error("Admission Tool exposed an invalid ResearchRun id");
  }
  await expect(page.getByRole("article", {
    name: /Tool get_research_run:/,
  })).toHaveCount(0);
  const proposalSurface = page.getByRole("region", {
    name: "Alpha proposal: Low-volatility factor",
  });
  await expect(proposalSurface).toContainText("Chat-owned");
  await expect(proposalSurface).toContainText("Factor Evaluation");
  await expect(proposalSurface).toContainText("top1000");
  await expect(proposalSurface).toContainText("rank(-abs(pct_change(close, 1)))");
  const formulaSurface = page.getByRole("region", { name: "Proposed formula" });
  const copyFormula = formulaSurface.getByRole("button", { name: "Copy" });
  await copyFormula.click();
  await expect(formulaSurface.getByText("Formula copied", { exact: true })).toBeAttached();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    "rank(-abs(pct_change(close, 1)))",
  );
  const acceptedSurface = page.getByRole("region", {
    name: `ResearchRun ${runId}: queued`,
  });
  await expect(acceptedSurface).toContainText("Accepted by ThesisTrace Core");
  const acceptedNavigation = page.getByRole("link", {
    name: "Open authoritative ResearchRun",
  }).first();
  await expect(acceptedNavigation).toHaveAttribute("href", `/research-runs/${runId}`);
  await expect(page.getByRole("article", { name: "Research surface" })).toHaveCount(2);

  await expect.poll(async () => {
    const response = await page.request.get(`/api/research-runs/${runId}`);
    if (!response.ok()) return `http:${response.status()}`;
    return ((await response.json()) as { status: string }).status;
  }, { timeout: 90_000 }).toBe("succeeded");

  const durableFacts = researchRunDatabaseFacts(runId);
  expect(durableFacts).toMatchObject({
    folder_id: "folder_default",
    formula_source: "rank(-abs(pct_change(close, 1)))",
    research_kind: "factor_evaluation",
    researcher_id: researcher.id,
  });
  expect(durableFacts.data_generation_id).toMatch(/^[a-f0-9]{64}$/);

  await message.fill(scriptedResumeResearchPrompt);
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(agentRunStatus(page)).toHaveText("Run complete", { timeout: 30_000 });

  const detail = await page.request.get(`/api/research-runs/${runId}`);
  expect(detail.status()).toBe(200);
  const detailBody = await detail.json() as {
    input: { formula: string; hypothesis: string };
    result: {
      factor: {
        horizons: { "5": { summary: {
          rank_ic: { mean: number | null };
          top_bottom_return: number | null;
        } } };
      };
    };
  };
  expect(detailBody).toMatchObject({
    id: runId,
    input: {
      formula: "rank(-abs(pct_change(close, 1)))",
      neutralization: "none",
      research_kind: "factor_evaluation",
      universe: "top1000",
    },
    result: {
      provenance: {
        research_kind: "factor_evaluation",
        research_run_id: runId,
      },
    },
    status: "succeeded",
  });
  const factorSummary = detailBody.result.factor.horizons["5"].summary;
  const result = page.locator(".chat-message-assistant .chat-assistant-markdown").last();
  await expect(result).toContainText(detailBody.input.hypothesis);
  await expect(result).toContainText(detailBody.input.formula);
  const rankIc = factorSummary.rank_ic.mean === null
    ? "Unavailable"
    : factorSummary.rank_ic.mean.toFixed(4);
  const spread = factorSummary.top_bottom_return === null
    ? "Unavailable"
    : `${(factorSummary.top_bottom_return * 100).toFixed(2)}%`;
  await expect(result).toContainText(rankIc);
  await expect(result).toContainText(spread);
  await expect(result.locator("li")).not.toHaveCount(0);
  await expect(result.locator("a.chat-markdown-run-link")).toHaveAttribute("href", runHref);
  const resultSurface = page.getByRole("article", { name: "Research surface" }).last();
  await expect(resultSurface.getByRole("region", {
    name: `ResearchRun ${runId}: succeeded`,
  })).toContainText("Authoritative immutable Result is available");
  await expect(resultSurface.getByRole("region", {
    name: "Factor Evaluation result",
  })).toContainText(rankIc);
  await expect(resultSurface).toContainText(spread);
  const resultDisclosure = resultSurface.getByRole("button", {
    name: "Inspect result metrics",
  });
  await expect(resultDisclosure).toHaveAttribute("aria-expanded", "false");
  await resultDisclosure.click();
  await expect(resultDisclosure).toHaveAttribute("aria-expanded", "true");
  const resultTable = resultSurface.getByRole("table", {
    name: "Authoritative factor metrics",
  });
  await expect(resultTable).toContainText("5-session Rank IC");
  await expect(resultTable).toContainText(rankIc);
  const provenanceDisclosure = resultSurface.getByRole("button", {
    name: "Inspect provenance",
  });
  await provenanceDisclosure.click();
  await expect(provenanceDisclosure).toHaveAttribute("aria-expanded", "true");
  await expect(resultSurface).toContainText("Result section");
  await expect(resultSurface).toContainText("factor");
  await expect(resultSurface.getByRole("link", {
    name: "Open authoritative ResearchRun",
  })).toHaveAttribute("href", runHref);
  await expect(page.getByRole("article", { name: "Research surface" })).toHaveCount(3);
  await expect(resultSurface.getByRole("button", {
    name: /Submit|Retry|Cancel|Stop|Delete/,
  })).toHaveCount(0);

  await message.fill(scriptedStrategyPrompt);
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByRole("article", {
    name: "Tool submit_research_run: Completed",
  })).toHaveCount(2, { timeout: 30_000 });
  await expect(agentRunStatus(page)).toHaveText("Run complete", { timeout: 90_000 });
  const strategyAdmission = page.getByRole("article", {
    name: "Tool submit_research_run: Completed",
  }).last();
  const strategyRunHref = await strategyAdmission.locator("a.chat-tool-resource")
    .getAttribute("href");
  if (strategyRunHref === null) throw new Error("Strategy Tool exposed no safe Run route");
  const strategyRunId = strategyRunHref.split("/").at(-1);
  if (strategyRunId === undefined || !/^run_[a-f0-9]{20}$/.test(strategyRunId)) {
    throw new Error("Strategy Tool exposed an invalid ResearchRun id");
  }
  expect(strategyRunId).not.toBe(runId);
  const trackResponse = await page.request.post(
    `/api/research-runs/${strategyRunId}/daily-tracks`,
    {
      data: { request_id: `chat-independence-${strategyRunId}` },
      headers: sameOriginHeaders(),
    },
  );
  expect(trackResponse.status()).toBe(201);
  const track = await trackResponse.json() as { id: string };
  expect(track.id).toMatch(/^track_[a-f0-9]{20}$/);
  const stopTrack = await page.request.post(`/api/daily-tracks/${track.id}/stop`, {
    data: { request_id: `chat-independence-stop-${track.id}` },
    headers: sameOriginHeaders(),
  });
  expect(stopTrack.status()).toBe(202);
  await expect.poll(async () => {
    const response = await page.request.get(`/api/daily-tracks/${track.id}`);
    if (!response.ok()) return `http:${response.status()}`;
    return ((await response.json()) as { status: string }).status;
  }, { timeout: 30_000 }).toBe("stopped");
  const dailyTrackBeforeDelete = await (
    await page.request.get(`/api/daily-tracks/${track.id}`)
  ).json() as Record<string, unknown>;
  expect(dailyTrackBeforeDelete).toMatchObject({
    id: track.id,
    origin: { seed_run_id: strategyRunId },
    status: "stopped",
  });

  const durableUrl = page.url();
  const agentRunsBeforeReplay = agentRunRequests;
  const replaySessionId = new URL(durableUrl).searchParams.get("session");
  if (replaySessionId === null) throw new Error("Durable Research Chat exposed no Session id");
  const surfaceFactsBeforeReplay = agentChatDatabaseFacts(replaySessionId);
  expect(surfaceFactsBeforeReplay.a2ui).toBeGreaterThanOrEqual(6);
  await expect(page.getByRole("article", { name: "Research surface" }))
    .toHaveCount(surfaceFactsBeforeReplay.a2ui);
  await page.reload();
  await expect(page).toHaveURL(durableUrl);
  await expect(agentRunStatus(page)).toHaveText("Run complete");
  await expect(page.getByRole("article", { name: "Research surface" }))
    .toHaveCount(surfaceFactsBeforeReplay.a2ui);
  await expect(page.getByRole("region", {
    name: "Alpha proposal: Low-volatility factor",
  })).toContainText("Chat-owned");
  await expect(page.getByRole("region", {
    name: "Factor Evaluation result",
  })).toContainText(rankIc);
  expect(agentRunRequests).toBe(agentRunsBeforeReplay);
  await expect(page.locator(".chat-tool-resource").filter({ hasText: runId }).first())
    .toHaveAttribute("href", runHref);
  await expect(page.locator(".chat-message-assistant .chat-assistant-markdown").filter({
    hasText: rankIc,
  }).last())
    .toContainText(rankIc);
  const chatSessionId = replaySessionId;
  const agentFactsBeforeDelete = agentChatDatabaseFacts(chatSessionId);
  expect(agentFactsBeforeDelete.sessions).toBe(1);
  expect(agentFactsBeforeDelete.threads).toBe(1);
  expect(agentFactsBeforeDelete.messages).toBeGreaterThan(0);
  expect(agentFactsBeforeDelete.runs).toBeGreaterThanOrEqual(2);
  expect(agentFactsBeforeDelete.a2ui).toBeGreaterThanOrEqual(5);
  await page.setViewportSize({ height: 900, width: 768 });
  const durableRunLink = page.locator("a.chat-markdown-run-link").last();
  await durableRunLink.scrollIntoViewIfNeeded();
  const touchTarget = await durableRunLink.boundingBox();
  expect(touchTarget?.width).toBeGreaterThanOrEqual(44);
  expect(touchTarget?.height).toBeGreaterThanOrEqual(44);

  const foreign = await createResearcher(page, `foreign-${runId}@example.test`);
  const foreignBootstrap = await page.request.post("/api/researcher/bootstrap", {
    data: {},
    headers: sameOriginHeaders(),
  });
  expect(foreignBootstrap.status()).toBe(200);
  expect(foreign.id).not.toBe(researcher.id);
  expect((await page.request.get(`/api/research-runs/${runId}`)).status()).toBe(404);
  expect((await page.request.get(`/api/daily-tracks/${track.id}`)).status()).toBe(404);
  await page.goto(durableUrl);
  await expect(page.getByRole("heading", { name: "Chat not found" })).toBeVisible();
  await expect(page.getByText(detailBody.input.hypothesis, { exact: true })).toHaveCount(0);
  await restoreResearcherSession(page, researcher);
  expect((await page.request.get(`/api/research-runs/${runId}`)).status()).toBe(200);
  expect((await page.request.get(`/api/daily-tracks/${track.id}`)).status()).toBe(200);

  await page.setViewportSize({ height: 900, width: 1280 });
  await page.goto(durableUrl);
  await expect(page.locator(".chat-message-assistant .chat-assistant-markdown").filter({
    hasText: rankIc,
  }).last())
    .toContainText(rankIc);
  const currentTitleText = await page.locator(".chat-session-title strong").textContent();
  const currentTitle = currentTitleText?.trim();
  if (currentTitle === undefined || currentTitle.length === 0) {
    throw new Error("Durable Research Chat exposed no title");
  }
  await page.getByRole("button", { name: `Actions for ${currentTitle}` }).click();
  await page.getByRole("menuitem", { name: "Delete Chat" }).click();
  const deleteDialog = page.getByRole("dialog", { name: "Delete Chat?" });
  await expect(deleteDialog).toContainText(
    "ResearchRuns, Results, and Daily Tracks remain independent and are not deleted.",
  );
  await expect(deleteDialog.getByRole("button", { name: "Cancel" })).toBeFocused();
  await deleteDialog.getByRole("button", { name: "Delete Chat" }).click();
  await expect(page).toHaveURL(/\/chat$/);
  await expect(page.getByRole("heading", { name: "Turn an investment idea into Alpha" }))
    .toBeVisible();
  await expect(page.getByRole("link", { name: "New Chat", exact: true })).toBeFocused();
  const deletedSessionResponse = await page.request.get(
    `/api/agent/sessions/${chatSessionId}`,
    { headers: sameOriginHeaders() },
  );
  expect(deletedSessionResponse.status()).toBe(404);
  expect(await deletedSessionResponse.json()).toEqual({
    code: "CHAT_SESSION_NOT_FOUND",
  });

  const agentFactsAfterDelete = agentChatDatabaseFacts(
    chatSessionId,
    agentFactsBeforeDelete.run_ids,
  );
  expect(agentFactsAfterDelete).toEqual({
    a2ui: 0,
    messages: 0,
    observational_memory: 0,
    run_ids: [],
    runs: 0,
    sessions: 0,
    snapshots: 0,
    threads: 0,
  });

  await page.goto(durableUrl);
  await expect(page.getByRole("heading", { name: "Chat not found" })).toBeVisible();
  const detailAfterChatDelete = await page.request.get(`/api/research-runs/${runId}`);
  expect(detailAfterChatDelete.status()).toBe(200);
  expect(await detailAfterChatDelete.json()).toEqual(detailBody);
  const dailyTrackAfterChatDelete = await page.request.get(`/api/daily-tracks/${track.id}`);
  expect(dailyTrackAfterChatDelete.status()).toBe(200);
  expect(await dailyTrackAfterChatDelete.json()).toEqual(dailyTrackBeforeDelete);

  await page.goto(runHref);
  await expect(page).toHaveURL(new RegExp(`/research-runs/${runId}$`));
  await expect(page.locator(".research-run-facts")).toContainText("Status succeeded");
  await expect(page.getByRole("heading", { name: "Factor Summary" })).toBeVisible();
});

test("a lost admission response replays the same effect and resumes the one Core run", async ({
  page,
  researcher,
}) => {
  test.setTimeout(240_000);
  await page.goto("/chat");
  const message = page.getByRole("textbox", { name: "Message", exact: true });
  await message.fill(scriptedFactorSubmitOnlyPrompt);
  setProxyMode("mcp-fault-proxy", 8150, "tool-call", "disconnect-submit");
  try {
    await page.getByRole("button", { name: "Send message" }).click();
    await expect(agentRunStatus(page)).toHaveText("Run failed", { timeout: 30_000 });
    await expect(page.getByRole("article", {
      name: "Tool submit_research_run: Failed",
    })).toBeVisible();
    const disconnectedState = proxyState("mcp-fault-proxy", 8150);
    expect(disconnectedState.tool_call_mode).toBe("disconnect-submit");
    expect(Number(disconnectedState.disconnected_submit_responses)).toBeGreaterThanOrEqual(1);
    expect(disconnectedState.disconnected_tool_responses).toBe(
      disconnectedState.disconnected_submit_responses,
    );
    setProxyMode("mcp-fault-proxy", 8150, "tool-call", "pass");

    await expect.poll(
      () => researchAdmissionDatabaseFacts(researcher.id),
      { timeout: 30_000 },
    ).toMatchObject({ admission_count: 1, run_count: 1 });
    const admitted = researchAdmissionDatabaseFacts(researcher.id);
    if (admitted === null) throw new Error("Admission response loss created no Core receipt");
    expect(admitted.request_id).toMatch(/^agent_[a-f0-9]{32}_research_v1$/);
    expect(admitted.run_id).toMatch(/^run_[a-f0-9]{20}$/);

    await expect.poll(async () => {
      const response = await page.request.get(`/api/research-runs/${admitted.run_id}`);
      if (!response.ok()) return `http:${response.status()}`;
      return ((await response.json()) as { status: string }).status;
    }, { timeout: 90_000 }).toBe("succeeded");

    await message.fill(scriptedResumeResearchPrompt);
    await page.getByRole("button", { name: "Send message" }).click();
    await expect(agentRunStatus(page)).toHaveText("Run complete", { timeout: 60_000 });
    const replayedAdmission = page.getByRole("article", {
      name: "Tool submit_research_run: Completed",
    });
    await expect(replayedAdmission.locator("a.chat-tool-resource")).toHaveAttribute(
      "href",
      `/research-runs/${admitted.run_id}`,
    );
    await expect(page.locator(".chat-message-assistant .chat-assistant-markdown").last())
      .toContainText("rank(-abs(pct_change(close, 1)))");

    expect(researchAdmissionDatabaseFacts(researcher.id)).toMatchObject({
      admission_count: 1,
      request_id: admitted.request_id,
      run_count: 1,
      run_id: admitted.run_id,
      status: "succeeded",
    });
    expect(proxyState("mcp-fault-proxy", 8150).tool_call_mode).toBe("pass");
  } finally {
    setProxyMode("mcp-fault-proxy", 8150, "tool-call", "pass");
  }
});

test("the same Chat entry runs and explains a real Strategy Backtest", async ({
  page,
  researcher,
}) => {
  test.setTimeout(240_000);
  await page.goto("/chat");
  const message = page.getByRole("textbox", { name: "Message", exact: true });
  await message.fill(scriptedStrategyPrompt);
  await page.getByRole("button", { name: "Send message" }).click();

  await expect(agentRunStatus(page)).toHaveText("Run complete", { timeout: 90_000 });
  const admission = page.getByRole("article", {
    name: "Tool submit_research_run: Completed",
  });
  const runHref = await admission.locator("a.chat-tool-resource").getAttribute("href");
  if (runHref === null) throw new Error("Strategy admission exposed no safe Run route");
  const runId = runHref.split("/").at(-1);
  if (runId === undefined || !/^run_[a-f0-9]{20}$/.test(runId)) {
    throw new Error("Strategy admission exposed an invalid ResearchRun id");
  }
  await expect(page.getByRole("article", {
    name: "Tool get_research_run: Completed",
  }).last()).toContainText("succeeded");

  const detail = await page.request.get(`/api/research-runs/${runId}`);
  expect(detail.status()).toBe(200);
  const detailBody = await detail.json() as {
    input: { formula: string; hypothesis: string };
    result: { strategy: { summary: { metrics: {
      maximum_drawdown: { value: number };
      net_cumulative_return: number;
      sharpe: number;
    } } } };
  };
  expect(detailBody).toMatchObject({
    id: runId,
    input: {
      formula: "rank(-abs(pct_change(close, 1)))",
      holdings_count: 10,
      neutralization: "none",
      rebalance_every_sessions: 5,
      research_kind: "strategy_backtest",
      universe: "top1000",
    },
    result: {
      provenance: {
        research_kind: "strategy_backtest",
        research_run_id: runId,
      },
      strategy: {},
    },
    status: "succeeded",
  });
  const metrics = detailBody.result.strategy.summary.metrics;
  const result = page.locator(".chat-message-assistant .chat-assistant-markdown").last();
  await expect(result).toContainText(detailBody.input.hypothesis);
  await expect(result).toContainText(detailBody.input.formula);
  await expect(result).toContainText(metrics.sharpe.toFixed(4));
  await expect(result).toContainText(`${(metrics.net_cumulative_return * 100).toFixed(2)}%`);
  await expect(result).toContainText(`${(metrics.maximum_drawdown.value * 100).toFixed(2)}%`);
  await expect(result.locator("li")).not.toHaveCount(0);
  await expect(result.locator("a.chat-markdown-run-link")).toHaveAttribute("href", runHref);
  const durableFacts = researchRunDatabaseFacts(runId);
  expect(durableFacts).toMatchObject({
    folder_id: "folder_default",
    formula_source: "rank(-abs(pct_change(close, 1)))",
    research_kind: "strategy_backtest",
    researcher_id: researcher.id,
  });
  expect(durableFacts.data_generation_id).toMatch(/^[a-f0-9]{64}$/);

  await result.locator("a.chat-markdown-run-link").click();
  await expect(page).toHaveURL(new RegExp(`/research-runs/${runId}$`));
  await expect(page.getByRole("heading", { name: "Strategy Summary" })).toBeVisible();
});

test("Chat fails closed on a real Auth exchange timeout and recovers", async ({ page }) => {
  test.slow();
  await page.goto("/chat");
  const message = page.getByRole("textbox", { name: "Message", exact: true });
  const prompt = "Check whether the Agent can begin this research turn.";
  await message.fill(prompt);
  setProxyMode("auth-exchange-proxy", 8250, "exchange", "timeout");
  try {
    const runResponse = page.waitForResponse((response) =>
      new URL(response.url()).pathname.endsWith("/agent/research/run"),
    );
    await page.getByRole("button", { name: "Send message" }).click();
    expect((await runResponse).status()).toBe(200);
    await expect(agentRunStatus(page)).toHaveText("Run failed");
    await expect(page.getByRole("alert")).toHaveAttribute("data-failure-code", "MCP_TRANSIENT");
    await expect.poll(() => new URL(page.url()).searchParams.get("session")).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
    expect(proxyState("auth-exchange-proxy", 8250)).toMatchObject({
      delayed_exchange_responses: 1,
      exchange_mode: "timeout",
      exchange_requests: 1,
    });
  } finally {
    setProxyMode("auth-exchange-proxy", 8250, "exchange", "pass");
  }

  const exchangeRequestsBeforeReload = proxyState(
    "auth-exchange-proxy",
    8250,
  ).exchange_requests;
  await page.reload();
  await expect(page.getByText(prompt, { exact: true })).toBeVisible();
  await expect(agentRunStatus(page)).toHaveText("Run failed");
  await expect(message).toBeEnabled();
  expect(proxyState("auth-exchange-proxy", 8250)).toMatchObject({
    exchange_requests: exchangeRequestsBeforeReload,
  });
  await message.fill("Build a testable quality Alpha idea.");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(agentRunStatus(page)).toHaveText("Run complete");
  await expect(page.locator(".chat-message-assistant .chat-message-content")).toBeVisible();
});

test("a connected MCP Tool response disconnect becomes a durable failed Run and recovers", async ({ page }) => {
  test.slow();
  await page.goto("/chat");
  const message = page.getByRole("textbox", { name: "Message", exact: true });
  await message.fill("[scripted-tool-turn] Inspect the available research context.");
  setProxyMode("mcp-fault-proxy", 8150, "tool-call", "disconnect");
  try {
    const runResponse = page.waitForResponse((response) =>
      new URL(response.url()).pathname.endsWith("/agent/research/run"),
    );
    await page.getByRole("button", { name: "Send message" }).click();
    expect((await runResponse).status()).toBe(200);
    await expect(agentRunStatus(page)).toHaveText("Run failed");
    await expect(page.getByRole("alert")).toHaveAttribute("data-failure-code", "MCP_TRANSIENT");
    await expect.poll(() => new URL(page.url()).searchParams.get("session")).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
    const state = proxyState("mcp-fault-proxy", 8150);
    expect(state).toMatchObject({
      tool_call_mode: "disconnect",
    });
    for (const counter of [
      "disconnected_tool_responses",
      "discovery_requests",
      "tool_call_requests",
      "tool_list_requests",
    ]) {
      expect(Number(state[counter])).toBeGreaterThanOrEqual(1);
    }
    const logs = serviceLogs("agent");
    for (const privateValue of [
      "toolArgs",
      "data_overview",
      "authoring_constraints",
      "scripted-test-provider-secret",
      "session_token=",
      "access_token",
    ]) {
      expect(logs).not.toContain(privateValue);
    }
  } finally {
    setProxyMode("mcp-fault-proxy", 8150, "tool-call", "pass");
  }

  const durableUrl = page.url();
  await page.reload();
  await expect(page).toHaveURL(durableUrl);
  await expect(agentRunStatus(page)).toHaveText("Run failed");
  await expect(page.getByRole("article", {
    name: "Tool get_research_context: Failed",
  })).toBeVisible();
  await expect(message).toBeEnabled();
  await message.fill("[scripted-tool-turn] Inspect the available research context.");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByRole("article", {
    name: "Tool get_research_context: Completed",
  })).toBeVisible();
  await expect(agentRunStatus(page)).toHaveText("Run complete");
});

test("Agent readiness fails closed on Auth and Core metadata outages and recovers", async () => {
  test.slow();
  expect(agentReadinessStatus()).toBe(200);

  setProxyMode("auth-exchange-proxy", 8250, "readiness", "disconnect");
  try {
    await expect.poll(agentReadinessStatus, { timeout: 10_000 }).toBe(503);
    expect(proxyState("auth-exchange-proxy", 8250)).toMatchObject({
      readiness_mode: "disconnect",
    });
    expect(Number(
      proxyState("auth-exchange-proxy", 8250).disconnected_readiness_responses,
    )).toBeGreaterThanOrEqual(1);
  } finally {
    setProxyMode("auth-exchange-proxy", 8250, "readiness", "pass");
  }
  await expect.poll(agentReadinessStatus, { timeout: 10_000 }).toBe(200);

  setProxyMode("mcp-fault-proxy", 8150, "metadata", "disconnect");
  try {
    await expect.poll(agentReadinessStatus, { timeout: 10_000 }).toBe(503);
    expect(proxyState("mcp-fault-proxy", 8150)).toMatchObject({
      metadata_mode: "disconnect",
    });
    expect(Number(
      proxyState("mcp-fault-proxy", 8150).disconnected_metadata_responses,
    )).toBeGreaterThanOrEqual(1);
  } finally {
    setProxyMode("mcp-fault-proxy", 8150, "metadata", "pass");
  }
  await expect.poll(agentReadinessStatus, { timeout: 10_000 }).toBe(200);
});

type ResearchRunDatabaseFacts = Readonly<{
  data_generation_id: string;
  folder_id: string;
  formula_source: string;
  research_kind: string;
  researcher_id: string;
}>;

type ResearchAdmissionDatabaseFacts = Readonly<{
  admission_count: number;
  request_id: string;
  run_count: number;
  run_id: string;
  status: string;
}>;

type AgentChatDatabaseFacts = Readonly<{
  a2ui: number;
  messages: number;
  observational_memory: number;
  run_ids: readonly string[];
  runs: number;
  sessions: number;
  snapshots: number;
  threads: number;
}>;

const activeLayoutSessionId = "00000000-0000-4000-8000-00000000f501";
const activeLayoutRunId = "00000000-0000-4000-8000-00000000f502";
const menuFocusRunId = "00000000-0000-4000-8000-00000000f503";

function setAgentSessionActiveRun(threadId: string, active: boolean): void {
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
  if (!uuid.test(threadId)) {
    throw new Error("Active Agent menu Session requires a safe source id");
  }
  if (!active) {
    runAgentOwnerSql(`
      DELETE FROM agent.agent_run
      WHERE id = '${menuFocusRunId}'::uuid
        AND thread_id = '${threadId}'::uuid;
    `);
    return;
  }
  runAgentOwnerSql(`
    BEGIN;
    DELETE FROM agent.agent_run WHERE id = '${menuFocusRunId}'::uuid;
    INSERT INTO agent.agent_run (
      id, thread_id, request_fingerprint, model_key, provider_model_id,
      reasoning_effort, agent_build_revision, status
    ) VALUES (
      '${menuFocusRunId}'::uuid, '${threadId}'::uuid,
      decode(repeat('56', 32), 'hex'), 'scripted-research', 'scripted-v1',
      'medium', 'browser-menu-focus-test', 'running'
    );
    COMMIT;
  `);
}

function seedActiveAgentLayoutSession(sourceThreadId: string): void {
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
  if (!uuid.test(sourceThreadId)) {
    throw new Error("Active Agent layout Session requires a safe source id");
  }
  runAgentOwnerSql(`
    BEGIN;
    INSERT INTO agent.chat_session (
      id, researcher_id, selected_model_key, selected_reasoning_effort,
      created_at, updated_at
    )
    SELECT
      '${activeLayoutSessionId}'::uuid, researcher_id,
      selected_model_key, selected_reasoning_effort,
      pg_catalog.now(), pg_catalog.now()
    FROM agent.chat_session
    WHERE id = '${sourceThreadId}'::uuid;
    INSERT INTO agent."mastra_threads" (
      id, "resourceId", title, metadata, "createdAt", "updatedAt",
      "createdAtZ", "updatedAtZ"
    )
    SELECT
      '${activeLayoutSessionId}', "resourceId", 'Active layout session', NULL,
      pg_catalog.now()::timestamp without time zone,
      pg_catalog.now()::timestamp without time zone,
      pg_catalog.now(), pg_catalog.now()
    FROM agent."mastra_threads"
    WHERE id = '${sourceThreadId}';
    INSERT INTO agent.agent_run (
      id, thread_id, request_fingerprint, model_key, provider_model_id,
      reasoning_effort, agent_build_revision, status
    ) VALUES (
      '${activeLayoutRunId}'::uuid, '${activeLayoutSessionId}'::uuid,
      decode(repeat('55', 32), 'hex'), 'scripted-research', 'scripted-v1',
      'medium', 'browser-layout-test', 'running'
    );
    COMMIT;
  `);
}

function removeActiveAgentLayoutSession(): void {
  runAgentOwnerSql(`
    BEGIN;
    DELETE FROM agent.chat_session WHERE id = '${activeLayoutSessionId}'::uuid;
    DELETE FROM agent."mastra_threads" WHERE id = '${activeLayoutSessionId}';
    COMMIT;
  `);
}

function setAgentSessionTitle(threadId: string, title: string): void {
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(threadId)
    || !/^[A-Za-z ]{1,80}$/.test(title)
  ) {
    throw new Error("Agent Chat title setup requires safe values");
  }
  runAgentOwnerSql(`
    UPDATE agent."mastra_threads"
    SET title = '${title}',
        "updatedAt" = pg_catalog.clock_timestamp()::timestamp without time zone,
        "updatedAtZ" = pg_catalog.clock_timestamp()
    WHERE id = '${threadId}';
  `);
}

function runAgentOwnerSql(command: string): void {
  execFileSync(
    "docker",
    [
      "exec",
      "--env",
      "PGPASSWORD=owner-test-password",
      `${testProjectName()}-postgres-1`,
      "psql",
      "--username",
      "thesistrace_owner",
      "--dbname",
      "thesistrace",
      "--set",
      "ON_ERROR_STOP=1",
      "--command",
      command,
    ],
    { encoding: "utf8" },
  );
}

function agentChatDatabaseFacts(
  threadId: string,
  snapshotRunIds: readonly string[] = [],
): AgentChatDatabaseFacts {
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
  if (!uuid.test(threadId) || snapshotRunIds.some((runId) => !uuid.test(runId))) {
    throw new Error("Agent Chat database inspection requires safe ids");
  }
  const snapshotIds = snapshotRunIds.length === 0
    ? "ARRAY[]::text[]"
    : `ARRAY[${snapshotRunIds.map((runId) => `'${runId}'`).join(", ")}]::text[]`;
  const output = execFileSync(
    "docker",
    [
      "exec",
      "--env",
      "PGPASSWORD=owner-test-password",
      `${testProjectName()}-postgres-1`,
      "psql",
      "--username",
      "thesistrace_owner",
      "--dbname",
      "thesistrace",
      "--tuples-only",
      "--no-align",
      "--command",
      `
        SELECT json_build_object(
          'a2ui', (
            SELECT count(*)::integer
            FROM agent.a2ui_message
            WHERE thread_id = '${threadId}'::uuid
          ),
          'messages', (
            SELECT count(*)::integer
            FROM agent."mastra_messages"
            WHERE thread_id = '${threadId}'
          ),
          'observational_memory', (
            SELECT count(*)::integer
            FROM agent."mastra_observational_memory"
            WHERE "threadId" = '${threadId}'
          ),
          'run_ids', COALESCE((
            SELECT json_agg(id::text ORDER BY id)
            FROM agent.agent_run
            WHERE thread_id = '${threadId}'::uuid
          ), '[]'::json),
          'runs', (
            SELECT count(*)::integer
            FROM agent.agent_run
            WHERE thread_id = '${threadId}'::uuid
          ),
          'sessions', (
            SELECT count(*)::integer
            FROM agent.chat_session
            WHERE id = '${threadId}'::uuid
          ),
          'snapshots', (
            SELECT count(*)::integer
            FROM agent."mastra_workflow_snapshot"
            WHERE run_id = ANY(${snapshotIds})
          ),
          'threads', (
            SELECT count(*)::integer
            FROM agent."mastra_threads"
            WHERE id = '${threadId}'
          )
        )::text
      `,
    ],
    {
      encoding: "utf8",
      killSignal: "SIGKILL",
      stdio: ["ignore", "pipe", "pipe"],
      timeout: 10_000,
    },
  ).trim();
  const parsed = JSON.parse(output) as unknown;
  if (
    parsed === null
    || typeof parsed !== "object"
    || Array.isArray(parsed)
    || !Object.hasOwn(parsed, "a2ui")
    || !Object.hasOwn(parsed, "messages")
    || !Object.hasOwn(parsed, "observational_memory")
    || !Object.hasOwn(parsed, "run_ids")
    || !Object.hasOwn(parsed, "runs")
    || !Object.hasOwn(parsed, "sessions")
    || !Object.hasOwn(parsed, "snapshots")
    || !Object.hasOwn(parsed, "threads")
  ) {
    throw new Error("Agent Chat database facts are invalid");
  }
  const record = parsed as Record<string, unknown>;
  const counts = [
    record.a2ui,
    record.messages,
    record.observational_memory,
    record.runs,
    record.sessions,
    record.snapshots,
    record.threads,
  ];
  if (
    !counts.every((count) => Number.isInteger(count) && Number(count) >= 0)
    || !Array.isArray(record.run_ids)
    || record.run_ids.some((runId: unknown) => typeof runId !== "string" || !uuid.test(runId))
  ) {
    throw new Error("Agent Chat database facts are invalid");
  }
  return record as AgentChatDatabaseFacts;
}

function researchRunDatabaseFacts(runId: string): ResearchRunDatabaseFacts {
  if (!/^run_[a-f0-9]{20}$/.test(runId)) {
    throw new Error("ResearchRun database inspection requires a safe id");
  }
  const output = execFileSync(
    "docker",
    [
      "exec",
      "--env",
      "PGPASSWORD=owner-test-password",
      `${testProjectName()}-postgres-1`,
      "psql",
      "--username",
      "thesistrace_owner",
      "--dbname",
      "thesistrace",
      "--tuples-only",
      "--no-align",
      "--command",
      `
        SELECT json_build_object(
          'data_generation_id', immutable_input->'data_admission'->>'generation_manifest_sha256',
          'folder_id', folder_id,
          'formula_source', immutable_input->>'formula_source',
          'research_kind', immutable_input->>'research_kind',
          'researcher_id', researcher_id::text
        )::text
        FROM research_runs.runs
        WHERE id = '${runId}'
      `,
    ],
    {
      encoding: "utf8",
      killSignal: "SIGKILL",
      stdio: ["ignore", "pipe", "pipe"],
      timeout: 10_000,
    },
  ).trim();
  const parsed = JSON.parse(output) as unknown;
  if (
    parsed === null
    || typeof parsed !== "object"
    || Array.isArray(parsed)
    || !("data_generation_id" in parsed)
    || !("folder_id" in parsed)
    || !("formula_source" in parsed)
    || !("research_kind" in parsed)
    || !("researcher_id" in parsed)
  ) {
    throw new Error("ResearchRun database facts are invalid");
  }
  return parsed as ResearchRunDatabaseFacts;
}

function researchAdmissionDatabaseFacts(
  researcherId: string,
): ResearchAdmissionDatabaseFacts | null {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(
    researcherId,
  )) {
    throw new Error("Research admission inspection requires a safe Researcher id");
  }
  const output = execFileSync(
    "docker",
    [
      "exec",
      "--env",
      "PGPASSWORD=owner-test-password",
      `${testProjectName()}-postgres-1`,
      "psql",
      "--username",
      "thesistrace_owner",
      "--dbname",
      "thesistrace",
      "--tuples-only",
      "--no-align",
      "--command",
      `
        SELECT json_build_object(
          'admission_count', (
            SELECT count(*)::integer
            FROM research_runs.admission_requests
            WHERE researcher_id = '${researcherId}'::uuid
          ),
          'request_id', admission.request_id,
          'run_count', (
            SELECT count(*)::integer
            FROM research_runs.runs
            WHERE researcher_id = '${researcherId}'::uuid
          ),
          'run_id', admission.run_id,
          'status', run.status
        )::text
        FROM research_runs.admission_requests AS admission
        JOIN research_runs.runs AS run ON run.id = admission.run_id
        WHERE admission.researcher_id = '${researcherId}'::uuid
        ORDER BY admission.created_at DESC
        LIMIT 1
      `,
    ],
    {
      encoding: "utf8",
      killSignal: "SIGKILL",
      stdio: ["ignore", "pipe", "pipe"],
      timeout: 10_000,
    },
  ).trim();
  if (output.length === 0) return null;
  const parsed = JSON.parse(output) as unknown;
  if (
    parsed === null
    || typeof parsed !== "object"
    || Array.isArray(parsed)
    || !("admission_count" in parsed)
    || !("request_id" in parsed)
    || !("run_count" in parsed)
    || !("run_id" in parsed)
    || !("status" in parsed)
  ) {
    throw new Error("Research admission database facts are invalid");
  }
  return parsed as ResearchAdmissionDatabaseFacts;
}

function agentReadinessStatus(): number {
  const output = execFileSync(
    "docker",
    [
      "exec",
      `${testProjectName()}-agent-1`,
      "node",
      "--input-type=module",
      "--eval",
      `
        const response = await fetch("http://127.0.0.1:8400/health/ready", {
          signal: AbortSignal.timeout(5_000),
        });
        process.stdout.write(String(response.status));
      `,
    ],
    {
      encoding: "utf8",
      killSignal: "SIGKILL",
      stdio: ["ignore", "pipe", "pipe"],
      timeout: 10_000,
    },
  );
  const status = Number(output.trim());
  if (!Number.isInteger(status)) throw new Error("Agent readiness returned no status");
  return status;
}

function serviceLogs(service: "agent"): string {
  const result = spawnSync(
    "docker",
    ["logs", `${testProjectName()}-${service}-1`],
    {
      encoding: "utf8",
      killSignal: "SIGKILL",
      stdio: ["ignore", "pipe", "pipe"],
      timeout: 10_000,
    },
  );
  if (result.status !== 0) {
    throw new Error(`Could not read ${service} logs`);
  }
  return `${result.stdout}${result.stderr}`;
}
