import { expect, test } from "./workbench-fixture";

test("history navigation keeps the selected conversation canvas through delayed opening", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  const session = {
    id: "00000000-0000-4000-8000-000000000101", title: "Greeting", message_title: null,
    activity_at: "2026-09-30T00:00:00.000000Z", created_at: "2026-09-30T00:00:00.000000Z",
    version: "2026-09-30T00:00:00.000Z", current_turn: null, latest_turn: null,
  };
  let releasePreferences = () => {};
  let releaseConnection = () => {};
  const preferences = new Promise<void>(resolve => { releasePreferences = resolve; });
  const connection = new Promise<void>(resolve => { releaseConnection = resolve; });
  await page.route("https://workbench.fixture/api/agent/**", async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path === "/api/agent/context-window") return route.fulfill({ json: {
      model_key: url.searchParams.get("model_key"), context_window: 258_000, input_tokens: null, measured_at: null,
    } });
    if (path === "/api/agent/sessions") return route.fulfill({ json: { sessions: [session], next_cursor: null } });
    if (path === `/api/agent/sessions/${session.id}`) return route.fulfill({ json: session });
    if (path === "/api/agent/models") return route.fulfill({ json: {
      default_model_key: "research-primary", models: [{ key: "research-primary", display_name: "Research Primary",
        default_reasoning_effort: "medium", reasoning_efforts: ["medium"] }],
    } });
    if (path === `/api/agent/sessions/${session.id}/preferences`) {
      await preferences;
      return route.fulfill({ json: { model_key: "research-primary", reasoning_effort: "medium", selection_mode: "manual" } });
    }
    if (path.startsWith("/api/agent/copilotkit")) {
      await connection;
      return route.fulfill({ status: 503, json: { error: "UNAVAILABLE" } });
    }
    return route.fallback();
  });
  try {
    await page.goto("/chat");
    const history = page.locator(".chat-session-list").getByRole("link", { name: "Greeting", exact: true });
    await expect(history).toBeVisible();
    await expect(page.locator(".ant-welcome")).toBeVisible();
    await expect(page.locator(".ant-welcome-description")).toHaveCount(0);
    const cards = page.getByRole("region", { name: "Research question examples", exact: true });
    await expect(cards.getByRole("button")).toHaveCount(4);
    for (const card of await cards.getByRole("button").all()) await expect(card).toBeDisabled();
    const main = (await page.locator("main.quantgrove-chat").boundingBox())!;
    const welcome = (await page.locator(".ant-welcome").boundingBox())!;
    const sender = (await page.locator(".ant-sender").boundingBox())!;
    const cardsBox = (await cards.boundingBox())!;
    expect(sender.y - welcome.y - welcome.height).toBe(40);
    expect(cardsBox.y - sender.y - sender.height).toBe(40);
    expect(sender.width - cardsBox.width).toBe(48);
    expect(Math.abs(welcome.x + welcome.width / 2 - main.x - main.width / 2)).toBeLessThanOrEqual(1);
    expect(Math.abs((welcome.y + cardsBox.y + cardsBox.height) / 2 - main.y - main.height / 2)).toBeLessThanOrEqual(1);
    const settingsRequested = page.waitForRequest(request => request.url().endsWith(`/sessions/${session.id}/preferences`));
    await history.click();
    await settingsRequested;
    await expect(page).toHaveURL(`/chat?session=${session.id}`);
    await expect(page.getByRole("main", { name: "Greeting", exact: true })).toBeVisible();
    await expect(page.getByRole("main", { name: "Greeting", exact: true }).locator(":scope > header")).toHaveCount(0);
    await expect(history).toHaveAttribute("aria-current", "page");
    await expect(page.locator(".ant-welcome")).toHaveCount(0);
    await expect(cards).toHaveCount(0);
    await expect(page.getByRole("textbox", { name: "Message", exact: true })).toBeDisabled();
    await page.screenshot({ path: testInfo.outputPath("history-opening.png") });

    releasePreferences();
    await expect(page.getByRole("button", { name: "Model Research Primary, reasoning Medium", exact: true })).toBeVisible();
    await expect(page.getByRole("main", { name: "Greeting", exact: true })).toHaveAttribute("aria-busy", "true");
    await expect(page.locator(".ant-welcome")).toHaveCount(0);
    await expect(page.getByRole("main", { name: "Greeting", exact: true })).toBeVisible();
    await expect(page.getByRole("main", { name: "Greeting", exact: true }).locator(":scope > header")).toHaveCount(0);

    releaseConnection();
    await expect(page.getByRole("alert")).toContainText("The Research Agent could not be reached.");
    await expect(page.getByRole("main", { name: "Greeting", exact: true })).toBeVisible();
    await expect(page.getByRole("main", { name: "Greeting", exact: true }).locator(":scope > header")).toHaveCount(0);
    await expect(page.locator(".ant-welcome")).toHaveCount(0);
    await expect(page).toHaveURL(`/chat?session=${session.id}`);
  } finally {
    releasePreferences();
    releaseConnection();
  }
});
