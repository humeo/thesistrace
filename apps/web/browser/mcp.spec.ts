import { expect, test } from "@playwright/test";
import { buildProductFixture } from "./build-product-fixture";
let fixture: Awaited<ReturnType<typeof buildProductFixture>>;
test.beforeAll(async () => { fixture = await buildProductFixture(new URL("./fixtures/mcp.tsx", import.meta.url), "McpFixture"); });
test("MCP authoring reference loads shared docs, recovers errors and preserves selection", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  let failDetail = true;
  const reads: string[] = [];
  await page.route("http://mcp.test/**", route => {
    const url = new URL(route.request().url());
    if (url.pathname === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    if (url.pathname.endsWith("/connections")) return route.fulfill({ json: { server_url: "https://quantgrove.test/mcp", apps: [] } });
    if (url.pathname.endsWith("/connection")) return route.fulfill({ json: { checked_at: "2026-10-04T00:00:00Z", tools: [{ name: "get_authoring_reference", description: "Read current reference" }] } });
    if (!url.pathname.endsWith("/authoring-reference")) return route.fulfill({ status: 404 });
    expect(route.request().method()).toBe("GET");
    reads.push(url.search);
    const topic = url.searchParams.get("topic");
    const symbol = url.searchParams.get("symbol");
    if (symbol && failDetail) { failDetail = false; return route.fulfill({ status: 503 }); }
    return route.fulfill({ json: {
      topic, title: "Current reference", overview: ["Read the current data and diagnose before submission."], found: true,
      symbols: topic === "python_sdk" && !symbol ? [{ symbol: "Data.history", description: "Read bounded history." }] : [],
      entry: symbol ? { symbol, description: "Read through this Close.", signature: "Data.history(self, field_id, days, *, instruments=None)", parameters: { field_id: "Canonical field ID, not a formula identifier." }, returns: "History", notes: ["Missing observations are None."], constraints: {}, data_schema: null, examples: [{ title: "History example", language: "python", source: "prices = data.history('price.close.adjusted', 2)", entrypoint: "Strategy", context: null }] } : null,
    } });
  });
  await page.goto("http://mcp.test/");
  await page.addStyleTag({ content: fixture.styles });
  await page.addScriptTag({ content: fixture.script });
  expect(reads).toHaveLength(0);
  await page.getByRole("button", { name: /Read the authoring reference/ }).click();
  await expect(page.getByText("Read the current data and diagnose before submission.")).toBeVisible();
  await page.getByRole("button", { name: "Python SDK", exact: true }).click();
  await page.getByRole("combobox", { name: "Reference member" }).click();
  await page.getByRole("option", { name: "Data.history", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("could not be loaded");
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByText("Canonical field ID, not a formula identifier.")).toBeVisible();
  await expect(page.getByText("prices = data.history('price.close.adjusted', 2)", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "简体中文", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "参考成员" })).toContainText("Data.history");
  await expect(page.getByText("Missing observations are None.")).toBeVisible();
  expect(reads.filter(read => read.includes("symbol=Data.history"))).toHaveLength(2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
for (const width of [1280, 1440]) {
  test(`MCP nested instructions, copy feedback and revoke recovery at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    let revokeFailure = true;
    let revokeCalls = 0;
    await page.route("http://mcp.test/**", route => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
      if (path.endsWith("/connections")) return route.fulfill({ json: { server_url: `https://quantgrove.example.test/${"research".repeat(32)}/mcp`, apps: [{ id: "00000000-0000-4000-8000-000000000001", client_id: "client-1", name: "Research assistant", scopes: ["research:read"], authorized_at: "2026-09-26T00:00:00Z" }] } });
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
    await expect(page.getByRole("tablist")).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Authorized apps", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Tool set", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Connect an assistant", exact: true })).toHaveCount(0);
    const prompt = page.getByRole("region", { name: "Setup prompt", exact: true });
    const promptText = prompt.getByRole("textbox", { name: "Setup prompt", exact: true });
    await expect(promptText).toBeVisible();
    await expect(promptText).toHaveValue(/^Add Quantgrove MCP to Codex using/);
    await expect(promptText).toHaveAttribute("readonly", "");
    await expect(prompt.getByRole("button", { name: "Copy", exact: true })).toBeVisible();
    await expect(page.getByRole("list", { name: "Connection steps" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Option 1: Set up with your assistant", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Option 2: Add with a command", exact: true })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Option 2: Add with a command", exact: true })).toBeVisible();
    await expect(page.getByLabel("Codex add command", { exact: true })).toBeVisible();
    await expect(page.getByText("codex mcp login quantgrove", { exact: true })).toBeVisible();
    await expect(page.getByText("Copy into a new conversation and follow your assistant's instructions to add the server and authorize access.", { exact: true })).toHaveCount(0);
    await expect(page.getByText("Then ask Codex to list the available Quantgrove tools.", { exact: true })).toHaveCount(0);
    for (const [commandLabel, copyLabel] of [["Codex add command", "Copy command"], ["Codex authorization command", "Copy login command"]]) {
      await expect(page.getByRole("button", { name: copyLabel, exact: true })).toHaveText("");
      await expect(page.getByRole("button", { name: copyLabel, exact: true }).locator("svg")).toHaveCount(1);
      const commandBox = await page.getByLabel(commandLabel, { exact: true }).boundingBox();
      const copyBox = await page.getByRole("button", { name: copyLabel, exact: true }).boundingBox();
      expect(commandBox).not.toBeNull();
      expect(copyBox).not.toBeNull();
      expect(copyBox!.x).toBeGreaterThanOrEqual(commandBox!.x + commandBox!.width);
      expect(Math.abs((copyBox!.y + copyBox!.height / 2) - (commandBox!.y + commandBox!.height / 2))).toBeLessThan(1);
    }
    await page.getByRole("button", { name: "Copy command", exact: true }).hover();
    await expect(page.locator('[data-slot="tooltip-content"]')).toHaveText("Copy");
    const setupBox = await page.getByRole("region", { name: "Connect an assistant", exact: true }).boundingBox();
    const appsBox = await page.getByRole("region", { name: "Authorized apps", exact: true }).boundingBox();
    const toolsBox = await page.getByRole("region", { name: "Tool set", exact: true }).boundingBox();
    expect(setupBox).not.toBeNull();
    expect(appsBox).not.toBeNull();
    expect(toolsBox).not.toBeNull();
    expect(appsBox!.y).toBeGreaterThan(setupBox!.y + setupBox!.height);
    expect(toolsBox!.y).toBeGreaterThan(appsBox!.y + appsBox!.height);
    const assistantHeading = await page.getByRole("heading", { name: "Option 1: Set up with your assistant", exact: true }).boundingBox();
    const commandHeading = await page.getByRole("heading", { name: "Option 2: Add with a command", exact: true }).boundingBox();
    expect(commandHeading!.x).toBeGreaterThan(assistantHeading!.x + assistantHeading!.width);
    expect(commandHeading!.y).toBe(assistantHeading!.y);
    await prompt.getByRole("button", { name: "Copy", exact: true }).click();
    await expect(page.locator('[data-slot="toast-title"]')).toContainText("Copy failed");
    await page.locator('[data-slot="toast-close"]').click();
    await page.getByText("Claude Code", { exact: true }).click();
    await expect(promptText).toHaveValue(/^Add Quantgrove MCP to Claude Code using/);
    await expect(page.getByLabel("Claude Code add command", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Claude Code authorization command", { exact: true })).toHaveText("/mcp");
    await expect(page.getByRole("button", { name: "Copy command", exact: true })).toBeVisible();
    expect(await promptText.evaluate(el => el.scrollHeight <= el.clientHeight && el.scrollWidth <= el.clientWidth)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const group = page.getByRole("group", { name: "Tool categories", exact: true }).getByRole("button", { name: "Research preparation 1 tool", exact: true });
    await expect(group).toHaveAttribute("aria-pressed", "true");
    const tool = page.getByRole("button", { name: /Check research readiness/ });
    await tool.click();
    await expect(page.getByText("get_research_context", { exact: true })).toBeVisible();
    await expect(promptText).toBeVisible();
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
    await expect(page.getByText("选择你的客户端。", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "方式一：让 AI 助手添加", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "方式二：使用命令添加", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "复制命令", exact: true })).toHaveText("");
    await expect(page.getByRole("button", { name: "复制登录命令", exact: true })).toHaveText("");
    await expect(page.getByText("复制到新对话，按助手指引添加服务并授权。", { exact: true })).toHaveCount(0);
    await expect(page.getByText("然后让 Claude Code 列出可用的 Quantgrove 工具。", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("region", { name: "设置提示", exact: true }).getByRole("button", { name: "复制", exact: true })).toBeVisible();
    await expect(page.getByRole("textbox", { name: "设置提示", exact: true })).toHaveValue(/^请使用 .* 将 Quantgrove MCP 添加到 Claude Code/);
    await expect(tool).toHaveCount(0);
    await expect(page.getByText("get_research_context", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.getByRole("button", { name: "English", exact: true }).click();
    await page.getByText("Other client", { exact: true }).click();
    await expect(page.getByRole("heading", { name: "Option 2: Add the server manually", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Copy URL", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Copy URL", exact: true })).toHaveText("");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    revokeFailure = false;
    await revoke.click();
    await dialog.getByRole("button", { name: "Revoke access", exact: true }).click();
    await expect(page.getByText("No authorized apps yet")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Authorized apps" })).toBeFocused();
  });
}

test("long authorization target stays readable and successful revoke focuses a stable heading during service check", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
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
  await dialog.getByRole("button", { name: "Revoke access", exact: true }).press("Enter");
  await expect(page.getByRole("heading", { name: "Authorized apps" })).toBeFocused();
  await expect(page.getByRole("heading", { name: "Authorized apps" })).toHaveCSS("outline-style", "none");
});

test("MCP discovery state has no black dashed frame", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.route("http://mcp.test/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    if (path.endsWith("/connections")) return route.fulfill({ json: { server_url: "https://quantgrove.example.test/mcp", apps: [] } });
    if (path.endsWith("/connection")) return;
    return route.fulfill({ status: 404 });
  });
  await page.goto("http://mcp.test/");
  await page.addStyleTag({ content: fixture.styles });
  await page.addScriptTag({ content: fixture.script });
  const discovery = page.locator('[data-slot="empty"]').filter({ hasText: "Discovering tools" });
  await expect(discovery).toBeVisible();
  await expect(discovery).toHaveCSS("border-top-style", "none");
});

test("tool directory selects discovered categories, supports keyboard navigation and refreshes the selected list", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  let tools = [
    { name: "get_research_context", description: "Context" },
    { name: "list_research_runs", description: "Runs" },
    { name: "get_research_run", description: "Run" },
    { name: "list_daily_tracks", description: "Tracks" },
    { name: "custom_tool", description: "Custom" },
  ];
  await page.route("http://mcp.test/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    if (path.endsWith("/connections")) return route.fulfill({ json: { server_url: "https://quantgrove.example.test/mcp", apps: [] } });
    if (path.endsWith("/connection")) return route.fulfill({ json: { checked_at: "2026-09-26T00:00:00Z", tools } });
    return route.fulfill({ status: 404 });
  });
  await page.goto("http://mcp.test/");
  await page.addStyleTag({ content: fixture.styles });
  await page.addScriptTag({ content: fixture.script });
  const categories = page.getByRole("group", { name: "Tool categories", exact: true });
  const preparation = categories.getByRole("button", { name: "Research preparation 1 tool", exact: true });
  const runs = categories.getByRole("button", { name: "Research runs 2 tools", exact: true });
  await expect(preparation).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: /Check research readiness/ })).toBeVisible();
  await preparation.focus();
  await page.keyboard.press("ArrowDown");
  await expect(runs).toBeFocused();
  await page.keyboard.press("Space");
  await expect(runs).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: /Browse research runs/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Check run progress/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Check research readiness/ })).toHaveCount(0);
  await page.getByRole("button", { name: "简体中文" }).click();
  await expect(page.getByRole("group", { name: "工具分类", exact: true }).getByRole("button", { name: "研究运行 2 个工具", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: /浏览研究运行/ })).toBeVisible();
  await page.getByRole("button", { name: "English", exact: true }).click();
  await categories.getByRole("button", { name: "Other tools 1 tool", exact: true }).click();
  await page.getByRole("button", { name: "Custom tool", exact: true }).click();
  await expect(page.getByText("custom_tool", { exact: true })).toBeVisible();
  tools = [{ name: "get_research_context", description: "Context" }];
  await page.getByRole("button", { name: "Check service", exact: true }).click();
  await expect(preparation).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: /Check research readiness/ })).toBeVisible();
  await expect(categories.getByRole("button", { name: "Other tools 1 tool", exact: true })).toHaveCount(0);
  tools = [];
  await page.getByRole("button", { name: "Check service", exact: true }).click();
  await expect(page.getByText("No tools available", { exact: true })).toBeVisible();
  await expect(categories).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
