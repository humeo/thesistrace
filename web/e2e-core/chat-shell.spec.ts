import { execFileSync, spawnSync } from "node:child_process";

import {
  createResearcher,
  expect,
  securityTest,
  test,
  testProjectName,
} from "./auth-fixture";

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
  const assistant = page.locator(".chat-message-assistant .chat-message-content");
  await expect(assistant).toBeVisible();
  const assistantText = await assistant.textContent();
  if (assistantText === null) throw new Error("Expected one assistant response");
  expect(assistantText.trim().length).toBeGreaterThan(0);
  expect(new TextEncoder().encode(assistantText).byteLength).toBeLessThanOrEqual(512);
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
    assistantText,
  );
  expect(runRequests).toHaveLength(1);
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
  await expect(page.getByRole("status")).toHaveText("Run complete");
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
    await expect(page.getByRole("status")).toHaveText("Run failed");
    await expect(page.getByRole("alert")).toHaveText(
      "The Research Agent could not complete this run.",
    );
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
  await expect(page.getByRole("status")).toHaveText("Run failed");
  await expect(message).toBeEnabled();
  expect(proxyState("auth-exchange-proxy", 8250)).toMatchObject({
    exchange_requests: exchangeRequestsBeforeReload,
  });
  await message.fill("Build a testable quality Alpha idea.");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByRole("status")).toHaveText("Run complete");
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
    await expect(page.getByRole("status")).toHaveText("Run failed");
    await expect(page.getByRole("alert")).toHaveText(
      "The Research Agent could not complete this run.",
    );
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
  await expect(page.getByRole("status")).toHaveText("Run failed");
  await expect(page.getByRole("article", {
    name: "Tool get_research_context: Failed",
  })).toBeVisible();
  await expect(message).toBeEnabled();
  await message.fill("[scripted-tool-turn] Inspect the available research context.");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByRole("article", {
    name: "Tool get_research_context: Completed",
  })).toBeVisible();
  await expect(page.getByRole("status")).toHaveText("Run complete");
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

type FaultProxyService = "auth-exchange-proxy" | "mcp-fault-proxy";
type FaultProxyResource = "exchange" | "metadata" | "readiness" | "tool-call";
type FaultProxyMode = "disconnect" | "pass" | "timeout";

function setProxyMode(
  service: FaultProxyService,
  port: 8250 | 8150,
  resource: FaultProxyResource,
  mode: FaultProxyMode,
): void {
  proxyRequest(
    service,
    port,
    `/__test/${resource}-mode`,
    JSON.stringify({ mode, reset: true }),
  );
}

function proxyState(
  service: FaultProxyService,
  port: 8250 | 8150,
): Record<string, unknown> {
  const parsed = JSON.parse(proxyRequest(service, port, "/__test/state")) as unknown;
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Fault proxy returned an invalid state document");
  }
  return parsed as Record<string, unknown>;
}

function proxyRequest(
  service: FaultProxyService,
  port: 8250 | 8150,
  path: string,
  body?: string,
): string {
  return execFileSync(
    "docker",
    [
      "exec",
      `${testProjectName()}-${service}-1`,
      "node",
      "--input-type=module",
      "--eval",
      `
        const [url, body] = process.argv.slice(1);
        const response = await fetch(url, {
          ...(body === undefined ? {} : {
            body,
            headers: { "content-type": "application/json" },
            method: "PUT",
          }),
          signal: AbortSignal.timeout(5_000),
        });
        if (!response.ok) process.exit(1);
        process.stdout.write(await response.text());
      `,
      `http://127.0.0.1:${port}${path}`,
      ...(body === undefined ? [] : [body]),
    ],
    {
      encoding: "utf8",
      killSignal: "SIGKILL",
      stdio: ["ignore", "pipe", "pipe"],
      timeout: 10_000,
    },
  );
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
