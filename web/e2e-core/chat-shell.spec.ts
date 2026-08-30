import { execFileSync, spawnSync } from "node:child_process";
import type { Page } from "@playwright/test";

import {
  createResearcher,
  expect,
  restoreResearcherSession,
  sameOriginHeaders,
  securityTest,
  test,
  testProjectName,
} from "./auth-fixture";

const scriptedFactorSubmitOnlyPrompt =
  "Submit a low-volatility Factor Evaluation and return as soon as ThesisTrace accepts it.";
const scriptedResumeResearchPrompt =
  "Resume the accepted ResearchRun from this Chat and explain its authoritative Result when available.";
const scriptedStrategyPrompt =
  "Backtest a low-volatility Alpha strategy using reliable ThesisTrace defaults.";

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
  await expect(agentRunStatus(page)).toHaveText("Agent disconnected");
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
  await expect(agentRunStatus(page)).toHaveText("Run complete");

  const response = await responsePromise;
  expect(response.status).toBe(200);
  expect(response.headers["content-type"]).toContain("text/event-stream");
  expect(runRequests).toHaveLength(1);

  const durableUrl = page.url();
  await page.reload();
  await expect(page).toHaveURL(durableUrl);
  await expect(agentRunStatus(page)).toHaveText("Ready");
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
});

test("an admitted Factor outlives its Agent Run and a later Chat Run explains the real Result", async ({
  page,
  researcher,
}) => {
  test.setTimeout(240_000);
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

  const durableUrl = page.url();
  await page.reload();
  await expect(page).toHaveURL(durableUrl);
  await expect(agentRunStatus(page)).toHaveText("Ready");
  await expect(page.locator(".chat-tool-resource").filter({ hasText: runId }).first())
    .toHaveAttribute("href", runHref);
  await expect(page.locator(".chat-message-assistant .chat-assistant-markdown").last())
    .toContainText(rankIc);
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
  await restoreResearcherSession(page, researcher);
  expect((await page.request.get(`/api/research-runs/${runId}`)).status()).toBe(200);

  await page.goto(durableUrl);
  await page.locator("a.chat-markdown-run-link").last().click();
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

type FaultProxyService = "auth-exchange-proxy" | "mcp-fault-proxy";
type FaultProxyResource = "exchange" | "metadata" | "readiness" | "tool-call";
type FaultProxyMode = "disconnect" | "disconnect-submit" | "pass" | "timeout";

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
