import { expect, test } from "./workbench-fixture";

for (const mode of ["default", "manual"] as const) {
  test(`reopening a session ${mode === "default" ? "follows current defaults" : "retains an available manual choice"}`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 960 });
    const session = {
      id: "00000000-0000-4000-8000-000000000101", title: "Saved model settings",
      activity_at: "2026-09-30T00:00:00.000000Z", created_at: "2026-09-30T00:00:00.000000Z",
      version: "2026-09-30T00:00:00.000Z", current_turn: null, latest_turn: null,
    };
    let defaultKey = "previous";
    await page.route("https://workbench.fixture/api/agent/**", async route => {
      const url = new URL(route.request().url());
    const path = url.pathname;
    if (path === "/api/agent/context-window") return route.fulfill({ json: {
      model_key: url.searchParams.get("model_key"), context_window: 258_000, input_tokens: null, measured_at: null,
    } });
      if (path === "/api/agent/sessions") return route.fulfill({ json: { sessions: [session], next_cursor: null } });
      if (path === `/api/agent/sessions/${session.id}`) return route.fulfill({ json: session });
      if (path === `/api/agent/sessions/${session.id}/preferences`) return route.fulfill({ json: {
        selection_mode: mode, model_key: "previous", reasoning_effort: "low",
      } });
      if (path === "/api/agent/models") return route.fulfill({ json: {
        default_model_key: defaultKey, models: [
          { key: "previous", display_name: "Previous model", default_reasoning_effort: "high", reasoning_efforts: ["low", "high"] },
          { key: "current", display_name: "Current model", default_reasoning_effort: "high", reasoning_efforts: ["low", "high", "max"] },
        ],
      } });
      if (path.startsWith("/api/agent/copilotkit")) return route.fulfill({ status: 503, json: { error: "UNAVAILABLE" } });
      return route.fallback();
    });
    await page.goto(`/chat?session=${session.id}`);
    await expect(page.getByRole("button", { name: `Model Previous model, reasoning ${mode === "default" ? "High" : "Low"}`, exact: true })).toBeVisible();
    defaultKey = "current";
    await page.reload();
    const picker = page.getByRole("button", {
      name: mode === "default" ? "Model Current model, reasoning High" : "Model Previous model, reasoning Low", exact: true,
    });
    await expect(picker).toBeVisible();
    await picker.click();
    const followDefault = page.getByRole("checkbox", { name: "Follow default settings", exact: true });
    if (mode === "default") {
      await expect(followDefault).toBeChecked();
      await followDefault.uncheck();
      await expect(followDefault).not.toBeChecked();
      await page.getByRole("slider").press("End");
      await expect(page.getByRole("button", { name: "Model Current model, reasoning Max", exact: true })).toBeVisible();
    } else {
      await expect(followDefault).not.toBeChecked();
    }
    await followDefault.check();
    await expect(page.getByRole("button", { name: "Model Current model, reasoning High", exact: true })).toBeVisible();
    await expect(followDefault).toBeChecked();
  });
}

test("a retired saved selection opens with the current default without requiring model selection", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  const session = {
    id: "00000000-0000-4000-8000-000000000102", title: "Retired model session",
    activity_at: "2026-09-30T00:00:00.000000Z", created_at: "2026-09-30T00:00:00.000000Z",
    version: "2026-09-30T00:00:00.000Z", current_turn: null, latest_turn: null,
  };
  await page.route("https://workbench.fixture/api/agent/**", async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path === "/api/agent/context-window") return route.fulfill({ json: {
      model_key: url.searchParams.get("model_key"), context_window: 258_000, input_tokens: null, measured_at: null,
    } });
    if (path === "/api/agent/sessions") return route.fulfill({ json: { sessions: [session], next_cursor: null } });
    if (path === `/api/agent/sessions/${session.id}`) return route.fulfill({ json: session });
    if (path === `/api/agent/sessions/${session.id}/preferences`) return route.fulfill({ json: {
      selection_mode: "manual", model_key: "gpt-6-luna", reasoning_effort: "high",
    } });
    if (path === "/api/agent/models") return route.fulfill({ json: {
      default_model_key: "gpt-6.1-sol", models: [{ key: "gpt-6.1-sol", display_name: "GPT-6.1 Sol",
        default_reasoning_effort: "high", reasoning_efforts: ["low", "medium", "high", "xhigh", "max"] }],
    } });
    if (path.startsWith("/api/agent/copilotkit")) return route.fulfill({ status: 503, json: { error: "UNAVAILABLE" } });
    return route.fallback();
  });
  await page.goto(`/chat?session=${session.id}`);
  const picker = page.getByRole("button", { name: "Model GPT-6.1 Sol, reasoning High", exact: true });
  await expect(picker).toBeVisible();
  await page.reload();
  await picker.click();
  await expect(page.getByRole("radio")).toHaveCount(1);
  await expect(page.getByRole("checkbox", { name: "Follow default settings", exact: true })).toBeChecked();
  await page.screenshot({ path: testInfo.outputPath("retired-selection-default.png") });
});
