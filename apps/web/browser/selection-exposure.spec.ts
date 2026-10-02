import { expect, test, type Page, type Locator } from "@playwright/test";
import { fontStylesheet, serveBrandAssets } from "./brand-assets";
import { buildProductFixture } from "./build-product-fixture";

let script: string;
let styles: string;

test("Run reveals and focuses a hidden invalid Python module without submitting", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 964 });
  let submissions = 0;
  await page.route("https://exposure.test/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/alpha/diagnostics") return route.fulfill({ json: { valid: true, diagnostics: [] } });
    if (path === "/api/research-runs") {
      submissions++;
      return route.fulfill({ status: 202, json: { id: "run_unexpected" } });
    }
    return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
  });
  await page.goto("https://exposure.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  const portfolio = page.getByRole("tab", { name: /Portfolio/ });
  await portfolio.click();
  await page.getByRole("radio", { name: "Code", exact: true }).check();
  await page.getByRole("textbox", { name: "Python source", exact: true }).fill("");
  await page.getByRole("tab", { name: /Signals/ }).click();
  await expect(page.getByRole("textbox", { name: "Python source", exact: true })).not.toBeVisible();
  await page.getByRole("button", { name: "Run backtest", exact: true }).click();
  await expect(portfolio).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("textbox", { name: "Python source", exact: true })).toBeFocused();
  await expect(page.getByRole("list", { name: "Complete these settings to continue:", exact: true })).toContainText("Python");
  expect(submissions).toBe(0);
});

const optionNames = {
  python: "Python module",
  equal_weight: "Equal weight", rank_weight: "Rank weight", inverse_volatility: "Inverse volatility",
} as const;
async function select(page: Page, control: Locator, value: keyof typeof optionNames) {
  await control.click();
  await page.getByRole("option", { name: optionNames[value], exact: true }).click();
}

async function formulaAllocation(page: Page) {
  await page.getByRole("combobox", { name: "How is total stock exposure set?", exact: true }).click();
  await page.getByRole("option", { name: "Formula based", exact: true }).click();
}

for (const width of [1280, 1440]) {
  test(`fees remain editable, validate beside the field and submit exactly at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 964 });
    const submissions: Record<string, unknown>[] = [];
    await page.route("https://exposure.test/**", route => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/alpha/diagnostics") return route.fulfill({ json: { valid: true, diagnostics: [] } });
      if (path === "/api/research-runs") {
        submissions.push(route.request().postDataJSON());
        return route.fulfill({ status: 202, json: { id: "run_costs" } });
      }
      return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    });
    const mount = async () => {
      await page.goto("https://exposure.test/");
      await page.addStyleTag({ content: styles });
      await page.addScriptTag({ content: script });
    };
    await mount();
    const costs = page.getByRole("region", { name: "Fees and slippage", exact: true });
    await expect(costs.getByRole("heading", { name: "Fees and slippage", exact: true })).toHaveCount(1);
    const toggle = costs.getByRole("button", { name: "Fees and slippage", exact: true });
    const slippage = page.getByLabel("Price slippage (basis points)", { exact: true });
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(slippage).not.toBeVisible();
    await toggle.click();
    await expect(slippage).toBeVisible();
    await expect(slippage).toHaveValue("0");
    await expect(page.getByLabel("Buy/sell commission rate", { exact: true })).toHaveValue("0.0003");
    await expect(page.getByLabel("Minimum commission per child order (CNY)", { exact: true })).toHaveValue("5");
    for (const [first, second] of [["Buy/sell commission rate", "Minimum commission per child order (CNY)"], ["Sell stamp duty rate", "Buy/sell transfer fee rate"]]) {
      const firstBox = (await costs.getByLabel(first, { exact: true }).boundingBox())!;
      const secondBox = (await costs.getByLabel(second, { exact: true }).boundingBox())!;
      expect(firstBox.y).toBe(secondBox.y);
      expect(secondBox.x).toBeGreaterThan(firstBox.x + firstBox.width);
    }
    await slippage.fill("10000");
    await toggle.click();
    await expect(slippage).not.toBeVisible();
    await page.getByRole("button", { name: "Run backtest", exact: true }).click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(slippage).toBeFocused();
    await expect(slippage).toHaveAttribute("aria-invalid", "true");
    await expect(page.locator("#cost-slippage_bps-error")).toContainText("below 10,000");
    expect(submissions).toHaveLength(0);
    await slippage.fill("15");
    await page.getByLabel("Minimum commission per child order (CNY)", { exact: true }).fill("2");
    await mount();
    await page.getByRole("radio", { name: "Python authoring", exact: true }).check();
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await toggle.click();
    await expect(slippage).toHaveValue("15");
    await expect(page.getByLabel("Minimum commission per child order (CNY)", { exact: true })).toHaveValue("2");
    await toggle.click();
    await expect(slippage).not.toBeVisible();
    await toggle.click();
    await expect(slippage).toHaveValue("15");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: `../../.local/browser-tests/simulation-costs-${width}.png`, fullPage: true });
    await page.getByRole("button", { name: "Run backtest", exact: true }).click();
    await expect.poll(() => submissions.length).toBe(1);
    expect(submissions[0]).toMatchObject({ strategy_mode: "direct", costs: {
      commission_rate_all_in: "0.0003", commission_min_cny: "2", stamp_duty_sell_rate: "0.0005",
      transfer_fee_rate: "0.00001", slippage_bps: "15",
    } });
  });
}

test("Factor admission ignores a second click before React paints the pending state", async ({ page }) => {
  let release!: () => void;
  const pending = new Promise<void>((resolve) => { release = resolve; });
  const submissions: Record<string, unknown>[] = [];
  await page.route("https://exposure.test/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/alpha/diagnostics") return route.fulfill({ json: { valid: true, diagnostics: [] } });
    if (path === "/api/research-runs") {
      submissions.push(route.request().postDataJSON());
      await pending;
      return route.fulfill({ status: 202, json: { id: "run_factor" } });
    }
    return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
  });
  await page.goto("https://exposure.test/?factor");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await page.getByRole("combobox", { name: "Universe" }).click();
  await page.getByRole("option", { name: "Top 300", exact: true }).click();
  await page.getByRole("button", { name: "Run evaluation" }).evaluate((button) => {
    (button as HTMLButtonElement).click();
    (button as HTMLButtonElement).click();
  });
  await expect.poll(() => submissions.length).toBe(1);
  release();
  expect(submissions).toHaveLength(1);
});

for (const width of [1280, 1440]) {
  test(`Framework modules retain independent drafts and locate errors at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 964 });
    const checks: Record<string, unknown>[] = [];
    const submissions: Record<string, unknown>[] = [];
    await page.route("https://exposure.test/**", route => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/alpha/diagnostics") return route.fulfill({ json: { valid: true, diagnostics: [] } });
      if (path === "/api/research/diagnostics") {
        checks.push(route.request().postDataJSON());
        return route.fulfill({ json: checks.length === 1 ? {
          valid: false, issues: [{ code: "STRATEGY_PROGRAM_INVALID", field: "modules.portfolio_construction.program.source",
            message: "portfolio_construction, line 1: SyntaxError: invalid syntax", severity: "error", range: null,
            details: { kind: "strategy_program", error_type: "SyntaxError", line: 1 } }],
        } : { valid: true, issues: [] } });
      }
      if (path === "/api/research-runs") {
        submissions.push(route.request().postDataJSON());
        return route.fulfill({ status: 202, json: { id: "run_framework" } });
      }
      return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    });
    const mount = async () => {
      await page.goto("https://exposure.test/");
      await page.addStyleTag({ content: styles });
      await page.addScriptTag({ content: script });
    };
    await mount();
    const alpha = page.locator("#research-stage-panel-alpha");
    const portfolio = page.locator("#research-stage-panel-portfolio_construction");
    await page.getByRole("tab", { name: /Signals/ }).click();
    await alpha.getByRole("radio", { name: "Code", exact: true }).check();
    await page.getByRole("tab", { name: /Portfolio/ }).click();
    await portfolio.getByRole("radio", { name: "Code", exact: true }).check();
    await expect(alpha.locator("#alpha-python-source")).toContainText("MomentumSignals");
    await expect(portfolio.getByRole("textbox", { name: "Python source", exact: true })).toContainText("BestSignal");
    await expect(page.getByLabel("Alpha formula", { exact: true })).not.toBeVisible();
    await expect(page.getByLabel("Holdings count", { exact: true })).not.toBeVisible();
    await portfolio.getByRole("textbox", { name: "Python source", exact: true }).fill("");
    await page.getByRole("button", { name: "Run backtest", exact: true }).click();
    await expect(portfolio.getByRole("textbox", { name: "Python source", exact: true })).toBeFocused();
    expect(submissions).toHaveLength(0);
    await mount();
    await page.getByRole("tab", { name: /Portfolio/ }).click();
    await expect(portfolio.getByRole("textbox", { name: "Python source", exact: true })).toHaveText("");
    await portfolio.getByRole("textbox", { name: "Python source", exact: true }).fill("class Broken(:");
    await page.getByRole("button", { name: "Check configuration" }).click();
    await expect(portfolio.locator("#portfolio_construction-python-source-error")).toContainText("line 1");
    await expect(alpha.locator("#alpha-python-source")).not.toHaveAttribute("aria-invalid", "true");
    await portfolio.getByRole("textbox", { name: "Python source", exact: true }).fill("from quantgrove import PortfolioConstruction\nclass Example(PortfolioConstruction):\n    def on_close(self, data, account): return None\n");
    await page.getByRole("button", { name: "Check configuration" }).click();
    await expect(page.getByText("Configuration is valid.", { exact: false })).toBeVisible();
    expect(checks[1]).toMatchObject({ strategy_mode: "framework", modules: {
      alpha: { kind: "python", program: { source: expect.stringContaining("class MomentumSignals(Alpha)") } },
      portfolio_construction: { kind: "python", program: { source: expect.stringContaining("def on_close") } },
      universe_selection: "dataset_universe/v1", risk_management: "no_risk/v1",
    } });
    for (const field of ["formula", "neutralization", "holdings_count", "selection_every_sessions", "exposure_expression", "program"]) {
      expect(checks[1]).not.toHaveProperty(field);
    }
    await portfolio.getByRole("button", { name: "Browse fields" }).click();
    await expect(page.getByRole("searchbox", { name: "Search fields" })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(portfolio.getByRole("button", { name: "Browse fields" })).toBeFocused();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: `../../.local/browser-tests/framework-authoring-${width}.png`, fullPage: true });
    await page.getByRole("button", { name: "Run backtest", exact: true }).click();
    await expect.poll(() => submissions.length).toBe(1);
    expect(submissions[0]).toMatchObject(checks[1]);
  });
}

for (const width of [1280, 1440]) {
  test(`Direct Python remains editable, validates and submits one active definition at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 964 });
    const checks: Record<string, unknown>[] = [];
    const submissions: Record<string, unknown>[] = [];
    await page.route("https://exposure.test/**", route => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/alpha/diagnostics") return route.fulfill({ json: { valid: true, diagnostics: [] } });
      if (path === "/api/research/diagnostics") {
        checks.push(route.request().postDataJSON());
        return route.fulfill({ json: checks.length === 1 ? {
          valid: false, issues: [{ code: "STRATEGY_PROGRAM_INVALID", field: "program.source",
            message: "program abcdef123456, line 1: SyntaxError: invalid syntax", severity: "error", range: null,
            details: { kind: "strategy_program", error_type: "SyntaxError", line: 1 } }],
        } : { valid: true, issues: [] } });
      }
      if (path === "/api/research-runs") {
        submissions.push(route.request().postDataJSON());
        return route.fulfill({ status: 202, json: { id: "run_direct" } });
      }
      return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    });
    const mount = async () => {
      await page.goto("https://exposure.test/");
      await page.addStyleTag({ content: styles });
      await page.addScriptTag({ content: script });
    };
    await mount();
    await page.getByRole("radio", { name: "Python authoring", exact: true }).check();
    await expect(page.getByRole("textbox", { name: "Python source", exact: true })).toContainText("class Momentum(Strategy)");
    await expect(page.getByLabel("Alpha formula", { exact: true })).not.toBeVisible();
    await expect(page.getByLabel("Holdings count", { exact: true })).not.toBeVisible();
    await page.getByRole("textbox", { name: "Python source", exact: true }).fill("");
    await page.getByRole("button", { name: "Run backtest", exact: true }).click();
    await expect(page.getByRole("list", { name: "Complete these settings to continue:", exact: true })).toContainText("Python");
    await expect(page.getByRole("textbox", { name: "Python source", exact: true })).toBeFocused();
    await page.getByRole("textbox", { name: "Python source", exact: true }).focus();
    await expect(page.locator("#python-source-error")).toContainText("Python");
    expect(submissions).toHaveLength(0);
    await mount();
    await expect(page.getByRole("textbox", { name: "Python source", exact: true })).toHaveText("");
    await page.getByRole("textbox", { name: "Python source", exact: true }).fill("class Broken(:");
    await page.getByRole("button", { name: "Check configuration" }).click();
    await expect(page.getByLabel("Configuration issues")).toContainText("line 1");
    await expect(page.locator("#python-source-error")).toContainText("line 1");
    const source = "from quantgrove import Strategy\nclass Example(Strategy):\n    def on_close(self, data, account): return None\n";
    await page.getByRole("textbox", { name: "Python source", exact: true }).fill(source);
    await expect(page.getByLabel("Configuration issues")).not.toBeVisible();
    await page.getByRole("button", { name: "Check configuration" }).click();
    await expect(page.getByText("Configuration is valid.", { exact: false })).toBeVisible();
    expect(checks[1]).toMatchObject({ strategy_mode: "direct", program: {
      source,
    } });
    expect(checks[1]).not.toHaveProperty("formula");
    expect(checks[1]).not.toHaveProperty("holdings_count");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: `../../.local/browser-tests/direct-python-${width}.png`, fullPage: true });
    await page.getByRole("button", { name: "Run backtest", exact: true }).click();
    await expect.poll(() => submissions.length).toBe(1);
    expect(submissions[0]).toMatchObject(checks[1]);
    expect(submissions[0]).not.toHaveProperty("exposure_expression");
  });
}

test("switching back to built-in Framework retains the inactive Python draft", async ({ page }) => {
  await page.route("https://exposure.test/**", route => route.fulfill({
    contentType: "text/html", body: '<div id="root"></div>',
  }));
  await page.goto("https://exposure.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await page.getByRole("radio", { name: "Python authoring", exact: true }).check();
  await page.getByRole("textbox", { name: "Python source", exact: true }).fill("private draft");
  await page.getByRole("radio", { name: "Modular authoring", exact: true }).check();
  await expect(page.getByRole("textbox", { name: "Python source", exact: true })).toHaveCount(0);
  await page.getByRole("tab", { name: /Signals/ }).click();
  await expect(page.getByLabel("Alpha formula", { exact: true })).toBeVisible();
  const draft = await page.evaluate(() => JSON.parse(localStorage.getItem("thesistrace.research-draft.exposure-test.folder_default")!));
  expect(draft.programSource).toBe("private draft");
  await page.getByRole("radio", { name: "Python authoring", exact: true }).check();
  await expect(page.getByRole("textbox", { name: "Python source", exact: true })).toHaveText("private draft");
});
test("Python editors keep completion, selection and undo across module, language and width changes", async ({ page }) => {
  await page.route("https://exposure.test/**", route => {
    if (new URL(route.request().url()).pathname === "/api/alpha/diagnostics") return route.fulfill({ json: { valid: true, diagnostics: [] } });
    return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
  });
  await page.goto("https://exposure.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await page.getByRole("tab", { name: /Signals/ }).click();
  const modes = page.getByRole("radiogroup", { name: "Selection signals authoring mode", exact: true });
  const code = modes.getByRole("radio", { name: "Code", exact: true });
  await code.check();
  const source = page.locator("#alpha-python-source");
  await source.fill("pri");
  await source.press("Control+Space");
  await expect(page.getByRole("option").filter({ hasText: /^print/ })).toBeVisible();
  await source.press("Escape");
  await source.fill("threshold = 1");
  await source.press("End");
  await page.keyboard.insertText(" + 2");
  await source.press("Home");
  for (let index = 0; index < 9; index++) await source.press("Shift+ArrowRight");
  const selectedText = () => source.evaluate(() => window.getSelection()?.toString());
  await expect.poll(selectedText).toBe("threshold");
  await page.getByRole("button", { name: "简体中文", exact: true }).dispatchEvent("click");
  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(source).toBeFocused();
  await expect.poll(selectedText).toBe("threshold");
  await page.getByRole("button", { name: "English", exact: true }).dispatchEvent("click");
  await modes.getByRole("radio", { name: "Configure", exact: true }).check();
  await expect(source).not.toBeVisible();
  await code.check();
  await source.focus();
  await expect.poll(selectedText).toBe("threshold");
  await page.keyboard.insertText("limit");
  await expect(source).toHaveText("limit = 1 + 2");
  await source.press("ControlOrMeta+z");
  await expect(source).toHaveText("threshold = 1 + 2");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test.beforeAll(async () => {
  test.setTimeout(120_000); // Fixture compilation is separate from each interaction timeout.
  ({ script, styles } = await buildProductFixture(new URL("./fixtures/selection-exposure.tsx", import.meta.url), "SelectionExposureFixture"));
});

test("a malformed local draft is shown as a new draft", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("thesistrace.research-draft.exposure-test.folder_default", "{broken");
  });
  await page.route("https://exposure.test/**", route => route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' }));
  await page.goto("https://exposure.test/?factor");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await expect(page.getByRole("heading", { name: "Choose a research type", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Factor Evaluation", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Strategy Backtest", exact: true })).toBeVisible();
  await expect(page.getByText("Draft saved in this browser")).toHaveCount(0);
});

for (const width of [1280, 1440]) {
  test(`Factor authoring retains manual dates and inserts a catalog field at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    const submissions: Record<string, unknown>[] = [];
    await page.route("https://exposure.test/**", route => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/alpha/diagnostics") return route.fulfill({ json: { valid: true, diagnostics: [] } });
      if (path === "/api/research/diagnostics") return route.fulfill({ json: { valid: true, issues: [] } });
      if (path === "/api/research-runs") {
        submissions.push(route.request().postDataJSON());
        return route.fulfill({ status: 202, json: { id: "run_factor" } });
      }
      return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    });
    await page.goto("https://exposure.test/?factor");
    await page.addStyleTag({ content: styles });
    await page.addScriptTag({ content: script });
    const editor = page.getByRole("textbox", { name: /^(Alpha formula|Alpha 公式)$/, exact: true });
    const authoring = page.getByRole("region", { name: "Alpha authoring" });
    const settings = page.getByRole("complementary", { name: "Run settings" });
    const start = page.getByRole("textbox", { name: "Research start date" });
    const end = page.getByRole("textbox", { name: "Research end date" });
    await expect(editor).toBeVisible();
    const authoringBox = (await authoring.boundingBox())!;
    const settingsBox = (await settings.boundingBox())!;
    if (width >= 960) expect(settingsBox.x).toBeGreaterThan(authoringBox.x + authoringBox.width);
    else expect(settingsBox.y).toBeGreaterThan(authoringBox.y + authoringBox.height);
    await start.fill("2025-02-29");
    await page.getByRole("button", { name: "Run evaluation" }).click();
    await expect(start).toHaveAttribute("aria-invalid", "true");
    await expect(page.getByRole("list", { name: "Complete these settings to continue:", exact: true })).toContainText("valid start date");
    expect(submissions).toHaveLength(0);
    await start.fill("2026-08-03");
    await expect(end).toHaveValue("2026-08-05");
    await page.getByRole("button", { name: "Open start date calendar" }).click();
    const calendar = page.getByRole("dialog", { name: "Open start date calendar" });
    await expect(calendar).toBeVisible();
    const calendarBox = (await calendar.boundingBox())!;
    expect(calendarBox.x).toBeGreaterThanOrEqual(0);
    expect(calendarBox.x + calendarBox.width).toBeLessThanOrEqual(width);
    const selectedDay = calendar.getByRole("button", { name: /Monday, August 3rd, 2026/ });
    await selectedDay.focus();
    await expect(selectedDay.locator("xpath=..")).toHaveAttribute("data-focused", "true");
    await page.keyboard.press("ArrowRight");
    const nextDay = calendar.getByRole("button", { name: /Tuesday, August 4th, 2026/ });
    await expect(nextDay).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(start).toHaveValue("2026-08-04");
    await start.fill("2026-08-03");
    await page.getByRole("button", { name: "Open start date calendar" }).click();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("button", { name: "Open start date calendar" })).toBeFocused();
    await page.getByRole("button", { name: "Browse fields" }).click();
    const browser = page.getByRole("dialog", { name: "Field browser" });
    await expect(browser).toBeVisible();
    await browser.getByRole("searchbox", { name: "Search fields" }).fill("close");
    await browser.getByRole("button", { name: "Insert into formula" }).click();
    await expect(browser).not.toBeVisible();
    await expect(editor).toContainText("closeclose");
    await expect(editor).toBeFocused();
    await page.getByRole("button", { name: "简体中文" }).click();
    await expect(page.getByLabel("研究开始日期")).toHaveValue("2026-08-03");
    await expect(editor).toContainText("closeclose");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`factor-authoring-${width}.png`), fullPage: true });
    await page.getByRole("button", { name: "运行评估" }).click();
    await expect.poll(() => submissions.length).toBe(1);
    expect(submissions[0]).toMatchObject({ formula: "closeclose", start_date: "2026-08-03", end_date: "2026-08-05" });
  });
}

for (const weighting of ["rank_weight", "inverse_volatility"] as const) {
test(`Exposure, ${weighting}, retained draft and submission share one source`, async ({ page }) => {
  const diagnostics: Record<string, unknown>[] = [];
  const submissions: Record<string, unknown>[] = [];
  const localContexts: string[] = [];
  await page.route("https://exposure.test/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/alpha/diagnostics") {
      localContexts.push(route.request().postDataJSON().context);
      return route.fulfill({ json: { valid: true, diagnostics: [] } });
    }
    if (path === "/api/research/diagnostics") {
      diagnostics.push(route.request().postDataJSON());
      return route.fulfill({ json: { valid: true, issues: [] } });
    }
    if (path === "/api/research-runs") {
      submissions.push(route.request().postDataJSON());
      return route.fulfill({ json: { id: "run_exposure" }, status: 202 });
    }
    return route.fulfill({ contentType: "text/html", body: `${fontStylesheet}<div id="root"></div>` });
  });
  const mount = async () => {
    await serveBrandAssets(page);
    await page.goto("https://exposure.test/");
    await page.addStyleTag({ content: styles });
    await page.addScriptTag({ content: script });
    await page.evaluate(() => document.fonts.ready);
  };
  await mount();
  await expect(page.getByText("Decide at Close, simulate at the next Open")).toBeVisible();
  const executionHelp = page.getByRole("button", { name: "About Execution timing" });
  await executionHelp.click();
  await expect(page.getByRole("dialog", { name: "Execution timing" })).toContainText("Trading restrictions can prevent fills");
  await executionHelp.press("Escape");

  await page.getByRole("tab", { name: /Portfolio/ }).click();
  await expect(page.getByRole("combobox", { name: "Portfolio weighting" })).toContainText("Equal weight");
  await select(page, page.getByLabel("Portfolio weighting", { exact: false }), weighting);
  if (weighting === "inverse_volatility") {
    await expect(page.getByLabel("Volatility window", { exact: false })).toHaveValue("20");
    await page.getByLabel("Volatility window", { exact: false }).fill("10");
  }
  await formulaAllocation(page);
  await expect(page.getByLabel("Exposure expression", { exact: true })).toHaveText("1");
  await expect(page.getByLabel("Total stock exposure (%)", { exact: true })).toHaveCount(0);
  await page.getByLabel("Exposure expression", { exact: true }).fill("0.7");
  await expect(page.getByLabel("Exposure expression", { exact: true })).toHaveText("0.7");
  await mount();

  await page.getByRole("tab", { name: /Portfolio/ }).click();
  await expect(page.getByRole("combobox", { name: "Portfolio weighting" })).toContainText(optionNames[weighting]);
  if (weighting === "inverse_volatility") {
    await expect(page.getByLabel("Volatility window", { exact: false })).toHaveValue("10");
  }
  await formulaAllocation(page);
  await expect(page.getByLabel("Exposure expression", { exact: true })).toHaveText("0.7");
  await page.getByLabel("Exposure expression", { exact: true }).fill("7 / 10");
  await expect(page.getByLabel("Total stock exposure (%)", { exact: true })).toHaveCount(0);

  await page.getByRole("button", { name: "Check configuration" }).click();
  await expect(page.getByText("Configuration is valid.", { exact: false })).toBeVisible();
  expect(diagnostics).toHaveLength(1);
  expect(diagnostics[0]).toMatchObject({ exposure_expression: "7 / 10", weighting, volatility_window: weighting === "inverse_volatility" ? 10 : 20, selection_every_sessions: 5, initial_cash_cny: "100000" });
  expect(diagnostics[0]).not.toHaveProperty("request_id");
  expect(submissions).toHaveLength(0);

  await page.getByLabel("Exposure expression", { exact: true }).fill("0");
  await expect(page.getByText("Configuration is valid.", { exact: false })).not.toBeVisible();
  await expect(page.getByLabel("Exposure expression", { exact: true })).toHaveText("0");
  await expect.poll(() => localContexts.includes("exposure")).toBe(true);
  await page.screenshot({ path: `../../.local/browser-tests/selection-${weighting}.png`, fullPage: true });

  await page.getByRole("button", { name: "Run backtest", exact: true }).click();
  await expect.poll(() => submissions.length).toBe(1);
  expect(submissions[0]).toMatchObject({ exposure_expression: "0", weighting, volatility_window: weighting === "inverse_volatility" ? 10 : 20, selection_every_sessions: 5, initial_cash_cny: "100000" });
  expect(submissions[0]).toHaveProperty("request_id");
  expect(submissions[0]).not.toHaveProperty("rebalance_every_sessions");
});

}

test("configuration checks show rejection and recover from an unavailable service", async ({ page }) => {
  let checks = 0;
  await page.route("https://exposure.test/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/alpha/diagnostics") return route.fulfill({ json: { valid: true, diagnostics: [] } });
    if (path === "/api/research/diagnostics") {
      checks++;
      if (checks === 1) return route.fulfill({ json: {
        valid: false, issues: [{ code: "EXPOSURE_OUT_OF_RANGE", field: "exposure_expression",
          message: "Exposure must be between zero and one.", severity: "error", range: null, details: { kind: "literal", expected: [0, 1], actual: "outside_finite_range" } }],
      } });
      if (checks === 2) return route.fulfill({ status: 503, body: "Unavailable" });
      return route.fulfill({ json: { valid: true, issues: [] } });
    }
    return route.fulfill({ contentType: "text/html", body: `${fontStylesheet}<div id="root"></div>` });
  });
  await serveBrandAssets(page);
    await page.goto("https://exposure.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
    await page.evaluate(() => document.fonts.ready);

  await page.getByRole("tab", { name: /Portfolio/ }).click();
  await formulaAllocation(page);
  await page.getByLabel("Exposure expression", { exact: true }).fill("1 + 0.1");

  const check = page.getByRole("button", { name: "Check configuration" });
  await check.click();
  await expect(page.getByLabel("Configuration issues")).toContainText("Position sizing formula");

  await page.getByLabel("Exposure expression", { exact: true }).fill("0.3");

  await expect(page.getByLabel("Configuration issues")).not.toBeVisible();
  await check.click();
  await expect(page.getByText("Configuration check is unavailable. Try again.")).toBeVisible();
  await expect(check).toBeEnabled();
  await check.click();
  await expect(page.getByText("Configuration is valid.", { exact: false })).toBeVisible();
  expect(checks).toBe(3);
});


test("Exposure completion excludes stock scope and keeps daily expression in the draft", async ({ page }) => {
  await page.route("https://exposure.test/**", route => {
    if (new URL(route.request().url()).pathname === "/api/alpha/diagnostics") {
      return route.fulfill({ json: { valid: true, diagnostics: [] } });
    }
    return route.fulfill({ contentType: "text/html", body: `${fontStylesheet}<div id="root"></div>` });
  });
  const mount = async () => {
    await serveBrandAssets(page);
    await page.goto("https://exposure.test/");
    await page.addStyleTag({ content: styles });
    await page.addScriptTag({ content: script });
    await page.evaluate(() => document.fonts.ready);
  };
  await mount();

  await page.getByRole("tab", { name: /Portfolio/ }).click();
  await formulaAllocation(page);
  const editor = page.getByLabel("Exposure expression", { exact: true });
  await editor.fill("");
  await editor.press("Control+Space");
  await expect(page.getByRole("listbox", { name: "Completions" }).getByRole("option").filter({ hasText: "universe_return" })).toBeVisible();
  await expect(page.getByRole("listbox", { name: "Completions" }).getByRole("option").filter({ hasText: "rank" })).toHaveCount(0);
  await expect(page.getByRole("listbox", { name: "Completions" }).getByRole("option").filter({ hasText: "close" })).toHaveCount(0);
  await editor.press("Escape");
  const expression = "if_else(universe_return() > 0, 1, 0.3)";
  await editor.fill(expression);
  await expect(page.getByLabel("Total stock exposure (%)", { exact: true })).toHaveCount(0);
  await mount();

  await page.getByRole("tab", { name: /Portfolio/ }).click();
  await expect(page.getByLabel("Exposure expression", { exact: true })).toHaveText(expression);

  await page.getByRole("tab", { name: /Signals/ }).click();
  const signal = page.getByLabel("Alpha formula", { exact: true });
  await signal.fill("");
  await signal.press("Control+Space");
  await expect(page.getByRole("listbox", { name: "Completions" }).getByRole("option").filter({ hasText: "rank" })).toBeVisible();
  await expect(page.getByRole("listbox", { name: "Completions" }).getByRole("option").filter({ hasText: "close" })).toBeVisible();
});

for (const weighting of ["equal_weight", "rank_weight"] as const) {
  test(`Leaving invalid inverse window for ${weighting} keeps a runnable form`, async ({ page }) => {
    const submissions: Record<string, unknown>[] = [];
    await page.route("https://exposure.test/**", async route => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/alpha/diagnostics") return route.fulfill({ json: { valid: true, diagnostics: [] } });
      if (path === "/api/research-runs") {
        submissions.push(route.request().postDataJSON());
        return route.fulfill({ json: { id: "run_window" }, status: 202 });
      }
      return route.fulfill({ contentType: "text/html", body: `${fontStylesheet}<div id="root"></div>` });
    });
    await serveBrandAssets(page);
    await page.goto("https://exposure.test/");
    await page.addStyleTag({ content: styles });
    await page.addScriptTag({ content: script });
    await page.evaluate(() => document.fonts.ready);

    await page.getByRole("tab", { name: /Portfolio/ }).click();
    const selector = page.getByLabel("Portfolio weighting", { exact: false });
    await select(page, selector, "inverse_volatility");
    await page.getByLabel("Volatility window", { exact: false }).fill("253");
    await page.getByRole("button", { name: "Run backtest", exact: true }).click();
    await expect(page.getByRole("list", { name: "Complete these settings to continue:", exact: true })).toContainText("Volatility window");
    await select(page, selector, weighting);
    await expect(page.getByLabel("Volatility window", { exact: false })).not.toBeVisible();
    await expect(page.getByRole("button", { name: "Check configuration" })).toBeEnabled();

  await page.getByRole("button", { name: "Run backtest", exact: true }).click();
    await expect.poll(() => submissions.length).toBe(1);
    expect(submissions[0]).toMatchObject({ weighting, volatility_window: 20 });
  });
}

for (const width of [1280, 1440]) {
  test(`Research workbench keeps settings compact and keyboard accessible at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 964 });
    await page.route("https://exposure.test/**", route => {
      if (new URL(route.request().url()).pathname === "/api/alpha/diagnostics") {
        return route.fulfill({ json: { valid: true, diagnostics: [] } });
      }
      return route.fulfill({ contentType: "text/html", body: `${fontStylesheet}<div id="root"></div>` });
    });
    await serveBrandAssets(page);
    await page.goto("https://exposure.test/");
    await page.addStyleTag({ content: styles });
    await page.addScriptTag({ content: script });
    await page.evaluate(() => document.fonts.ready);
    const settings = page.getByRole("complementary", { name: "Run settings", exact: true });
    await expect(settings).toBeVisible();
    await expect(settings.getByRole("heading", { name: "Backtest conditions", exact: true })).toHaveCSS("font-size", "16px");
    const notes = page.getByLabel("Research notes (optional)", { exact: true });
    await expect(notes).toBeVisible();
    const help = page.getByRole("button", { name: "Cash requirements" });
    await help.click();
    await expect(page.getByRole("dialog")).toContainText("two decimal places");
    await expect(page.getByRole("dialog").getByRole("heading")).toHaveCSS("font-size", "14px");
    await help.focus();
    await help.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await page.getByLabel("Initial cash (CNY)", { exact: true }).focus();
    await help.click();
    await expect(page.getByRole("dialog")).toBeVisible();

    await help.press("Escape");
    await expect(help).toBeFocused();
    await page.setViewportSize({ width, height: 500 });
    await page.getByRole("tab", { name: /Portfolio/ }).click();
    await formulaAllocation(page);
    for (const name of ["Weighting help", "Exposure formula help"]) {
      const exampleHelp = page.getByRole("button", { name, exact: true });
      await exampleHelp.evaluate((element) => element.scrollIntoView({ block: "center" }));
      await exampleHelp.click();
      const tooltip = page.getByRole("dialog", { name });
      await expect(tooltip).toContainText("50,000 CNY");
      const bounds = await tooltip.boundingBox();
      expect(bounds).not.toBeNull();
      expect(bounds!.y).toBeGreaterThanOrEqual(0);
      expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(500);
      expect(bounds!.x).toBeGreaterThanOrEqual(0);
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
      await exampleHelp.press("Escape");
      await expect(tooltip).toHaveCount(0);
    }
    await page.setViewportSize({ width, height: 964 });

    await page.getByLabel("Initial cash (CNY)", { exact: false }).fill("250000");
    await expect(page.getByLabel("Initial cash (CNY)", { exact: false })).toHaveValue("250000");
    await page.getByRole("tab", { name: /Signals/ }).click();
    await expect(page.getByRole("textbox", { name: "Alpha formula", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Back to research types", exact: true }).click();
    await page.getByRole("button", { name: "Factor Evaluation", exact: true }).click();
    await expect(page.getByRole("button", { name: "Run evaluation" })).toBeVisible();
    await expect(page.getByRole("complementary", { name: "Run settings" })).toBeVisible();
    await expect(page.getByLabel("Portfolio weighting", { exact: false })).not.toBeVisible();
    await page.getByLabel("Research notes (optional)", { exact: true }).fill("Compare the signal across market regimes.");
    const browse = page.getByRole("button", { name: "Browse fields", exact: true });
    const controlledPanelId = await browse.getAttribute("aria-controls");
    expect(controlledPanelId).toBe("research-fields-panel");
    await browse.click();
    const fields = page.getByRole("dialog", { name: "Field browser" });
    await expect(fields).toBeVisible();
    await expect(page.locator(`#${controlledPanelId}`)).toHaveCount(1);
    await expect(fields.getByRole("searchbox", { name: "Search fields" })).toBeFocused();
    await fields.getByRole("searchbox").fill("close");
    await expect(fields.getByRole("button", { name: /Adjusted close/ })).toBeVisible();
    await expect(fields.getByRole("region", { name: "Field details" })).toContainText("causal cumulative-adjusted close");
    await fields.getByRole("searchbox").fill("not_a_field");
    await expect(fields.getByText("No matching fields")).toBeVisible();
    await fields.getByRole("searchbox").fill("");
    await fields.getByRole("searchbox").press("Escape");
    await expect(fields).not.toBeVisible();
    await expect(browse).toBeFocused();
    await expect(page.getByRole("textbox", { name: "Alpha formula", exact: true })).toHaveText("close");
    await browse.click();
    await page.getByRole("button", { name: "Close field browser" }).click();
    await expect(fields).not.toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: `../../.local/browser-tests/research-workbench-${width}.png`, fullPage: true });
    await page.getByRole("button", { name: "简体中文", exact: true }).click();
    await page.evaluate(() => document.fonts.ready);
    await expect(page.getByRole("textbox", { name: "Alpha 公式", exact: true })).toHaveText("close");
    await expect(page.getByLabel("研究备注（可选）", { exact: true })).toHaveValue("Compare the signal across market regimes.");
    await expect(page.getByRole("button", { name: "运行评估", exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: test.info().outputPath(`research-zh-${width}.png`), fullPage: true });
  });
}

test("switching during configuration validation preserves inputs and translates the eventual failure", async ({ page }) => {
  let finish!: () => void;
  const pending = new Promise<void>((resolve) => { finish = resolve; });
  const requests: unknown[] = [];
  await page.route("https://exposure.test/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/alpha/diagnostics") return route.fulfill({ json: { valid: true, diagnostics: [] } });
    if (path === "/api/research/diagnostics") {
      requests.push(route.request().postDataJSON());
      await pending;
      return route.fulfill({ json: { valid: false, issues: [{
        code: "WINDOW_OUT_OF_RANGE", field: "formula", message: "Window must be between 1 and 252",
        severity: "error", details: { kind: "window", expected: [1, 252], actual: "253" },
        range: { start: { offset: 15, line: 1, column: 16 }, end: { offset: 18, line: 1, column: 19 } },
      }] } });
    }
    return route.fulfill({ contentType: "text/html", body: `${fontStylesheet}<div id="root"></div>` });
  });
  await serveBrandAssets(page);
  await page.goto("https://exposure.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await page.getByRole("tab", { name: /Signals/ }).click();
  await page.getByLabel("Alpha formula", { exact: true }).fill("ts_mean(close, 253)");

  const cash = page.locator("#initial-cash");
  await cash.fill("250000");
  await page.getByRole("button", { name: "Check configuration" }).click();
  await expect(page.getByText("Checking configuration…", { exact: true })).toBeVisible();
  await cash.focus();
  await page.getByRole("button", { name: "简体中文", exact: true }).dispatchEvent("click");
  await expect(page.getByText("正在检查配置…", { exact: true })).toBeVisible();
  await expect(cash).toBeFocused();
  await expect(page.getByRole("complementary", { name: "运行设置", exact: true })).toBeVisible();
  await expect(page.getByLabel("初始资金（CNY）", { exact: true })).toHaveValue("250000");
  finish();
  await expect(page.getByLabel("配置问题")).toContainText("窗口必须在 1 到 252 之间，实际为 253。");
  await page.getByRole("button", { name: "English", exact: true }).click();
  await expect(page.getByLabel("Configuration issues")).toContainText("Window must be between 1 and 252; received 253.");
  await expect(page.getByLabel("Alpha formula", { exact: true })).toHaveText("ts_mean(close, 253)");
  expect(requests).toHaveLength(1);
  expect(requests[0]).toMatchObject({ formula: "ts_mean(close, 253)", initial_cash_cny: "250000" });
  expect(requests[0]).not.toHaveProperty("locale");
});

for (const width of [1280, 1440]) {
  test(`Missing required settings are reachable from Run at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 964 });
    let submissions = 0;
    await page.route("https://exposure.test/**", route => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/alpha/diagnostics") return route.fulfill({ json: { valid: true, diagnostics: [] } });
      if (path === "/api/research-runs") { submissions++; return route.fulfill({ status: 202, json: { id: "run_valid" } }); }
      return route.fulfill({ contentType: "text/html", body: `${fontStylesheet}<div id="root"></div>` });
    });
    await serveBrandAssets(page);
    await page.goto("https://exposure.test/");
    await page.addStyleTag({ content: styles });
    await page.addScriptTag({ content: script });
    await page.evaluate(() => document.fonts.ready);
    await page.getByRole("tab", { name: "Portfolio", exact: true }).click();
    await expect(page.getByLabel("Holdings count", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Selection interval (trading days)", { exact: true })).toHaveValue("5");

    await page.getByLabel("Initial cash (CNY)", { exact: true }).fill("");

    await page.getByRole("button", { name: "Run backtest", exact: true }).click();
    await expect(page.getByRole("list", { name: "Complete these settings to continue:", exact: true })).toContainText("Initial cash");
    await expect(page.getByLabel("Initial cash (CNY)", { exact: true })).toBeFocused();
    expect(submissions).toBe(0);
    await page.getByLabel("Initial cash (CNY)", { exact: true }).fill("100000");
    await formulaAllocation(page);
    await page.getByLabel("Exposure expression", { exact: true }).fill("1.1");
    await page.getByRole("button", { name: "Run backtest", exact: true }).click();
    await expect(page.getByRole("list", { name: "Complete these settings to continue:", exact: true })).toContainText("between 0 and 1");
    await expect(page.getByLabel("Exposure expression", { exact: true })).toBeFocused();
    await expect(page.getByLabel("Exposure expression", { exact: true })).toHaveAttribute("aria-invalid", "true");
    await expect(page.getByLabel("Exposure expression", { exact: true })).toHaveAccessibleDescription(/between 0 and 1/);
    expect(submissions).toBe(0);
    const expression = "if_else(universe_return() > 0, 1, 0.3)";
    await page.getByLabel("Exposure expression", { exact: true }).fill(expression);

    await page.getByRole("tab", { name: /Signals/ }).click();
    await page.getByLabel("Alpha formula", { exact: true }).fill("");
    await page.getByRole("button", { name: "Run backtest", exact: true }).click();
    await expect(page.getByLabel("Alpha formula", { exact: true })).toBeFocused();
    expect(submissions).toBe(0);
    await page.getByLabel("Alpha formula", { exact: true }).fill("close");
    await page.getByRole("button", { name: "Run backtest", exact: true }).click();
    await expect.poll(() => submissions).toBe(1);
  });
}

for (const width of [1280, 1440]) {
  test(`built-in stop loss validates, persists and submits at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 964 });
    const submissions: Record<string, unknown>[] = [];
    await page.route("https://exposure.test/**", route => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/alpha/diagnostics") return route.fulfill({ json: { valid: true, diagnostics: [] } });
      if (path === "/api/research-runs") {
        submissions.push(route.request().postDataJSON());
        return route.fulfill({ status: 202, json: { id: "run_stop_loss" } });
      }
      return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    });
    const mount = async () => {
      await page.goto("https://exposure.test/");
      await page.addStyleTag({ content: styles });
      await page.addScriptTag({ content: script });
    };
    await mount();
    await page.getByRole("tab", { name: /Risk/ }).click();
    const threshold = page.getByRole("textbox", { name: "Stop loss (%)", exact: true });
    await page.getByRole("switch", { name: "Stop loss", exact: true }).check();
    await expect(threshold).toHaveValue("");
    await page.getByRole("button", { name: "About Stop loss", exact: true }).hover();
    await expect(page.getByRole("dialog", { name: "Stop loss", exact: true })).toContainText("next Open");
    await page.getByRole("button", { name: "About Stop loss", exact: true }).press("Escape");
    await threshold.fill("100");
    await page.getByRole("button", { name: "Run backtest", exact: true }).click();
    await expect(threshold).toBeFocused();
    await expect(threshold).toHaveAttribute("aria-invalid", "true");
    expect(submissions).toHaveLength(0);
    await threshold.fill("10");
    await mount();
    await page.getByRole("tab", { name: /Risk/ }).click();
    await expect(threshold).toHaveValue("10");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: `../../.local/browser-tests/stop-loss-${width}.png`, fullPage: true });
    await page.getByRole("button", { name: "Run backtest", exact: true }).click();
    await expect.poll(() => submissions.length).toBe(1);
    expect(submissions[0]).toMatchObject({ modules: { risk_management: {
      kind: "builtin_risk/v1", stop_loss_threshold: 0.1,
    } } });
  });
}

for (const width of [1280, 1440]) {
  test(`portfolio drawdown requires complete policy and persists at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 964 });
    const submissions: Record<string, unknown>[] = [];
    await page.route("https://exposure.test/**", route => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/alpha/diagnostics") return route.fulfill({ json: { valid: true, diagnostics: [] } });
      if (path === "/api/research-runs") {
        submissions.push(route.request().postDataJSON());
        return route.fulfill({ status: 202, json: { id: "run_drawdown" } });
      }
      return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    });
    const mount = async () => {
      await page.goto("https://exposure.test/");
      await page.addStyleTag({ content: styles });
      await page.addScriptTag({ content: script });
    };
    await mount();
    await page.getByRole("tab", { name: /Risk/ }).click();
    const threshold = page.getByLabel("Drawdown threshold (%)", { exact: true });
    await page.getByRole("switch", { name: "Portfolio drawdown limit", exact: true }).check();
    const cap = page.getByLabel("Maximum stock exposure (%)", { exact: true });
    const cooldown = page.getByLabel("Cooldown (trading sessions)", { exact: true });
    for (const input of [threshold, cap, cooldown]) await expect(input).toHaveValue("");
    await threshold.fill("10");
    await page.getByRole("button", { name: "Run backtest", exact: true }).click();
    await expect(cap).toBeFocused();
    await expect(cap).toHaveAttribute("aria-invalid", "true");
    expect(submissions).toHaveLength(0);
    await cap.fill("30");
    await cooldown.fill("2");
    await mount();
    await page.getByRole("tab", { name: /Risk/ }).click();
    await expect(threshold).toHaveValue("10");
    await expect(cap).toHaveValue("30");
    await expect(cooldown).toHaveValue("2");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: `../../.local/browser-tests/drawdown-${width}.png`, fullPage: true });
    await page.getByRole("button", { name: "Run backtest", exact: true }).click();
    await expect.poll(() => submissions.length).toBe(1);
    expect(submissions[0]).toMatchObject({ modules: { risk_management: {
      kind: "builtin_risk/v1", portfolio_drawdown: {
        drawdown_threshold: 0.1, maximum_stock_exposure: 0.3, cooldown_sessions: 2,
      },
    } } });
  });
}

test("Direct field browser inserts history at the selection and preserves undo", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.route("https://exposure.test/**", route => route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' }));
  await page.goto("https://exposure.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await page.getByRole("radio", { name: "Python authoring", exact: true }).check();
  const source = page.locator("#python-source");
  await source.fill("prices = ");
  await source.press("ControlOrMeta+End");
  const trigger = page.getByRole("button", { name: "Browse fields", exact: true });
  await trigger.click();
  const catalog = page.getByRole("dialog", { name: "Field browser", exact: true });
  await expect(catalog.getByRole("searchbox", { name: "Search fields", exact: true })).toBeFocused();
  await expect(catalog.getByRole("region", { name: "Field details", exact: true })).toContainText('data.history("price.close.adjusted", 10)');
  await catalog.getByRole("button", { name: "Insert data call", exact: true }).click();
  await expect(catalog).toHaveCount(0);
  await expect(source).toBeFocused();
  await expect(source).toHaveText('prices = data.history("price.close.adjusted", 10)');
  await source.press("ControlOrMeta+z");
  await expect(source).toHaveText("prices = ");
  await trigger.click();
  await page.keyboard.press("Escape");
  await expect(catalog).toHaveCount(0);
  await expect(trigger).toBeFocused();
});

test("formula configuration creates an exact strategy and preserves the draft", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  const submissions: Record<string, unknown>[] = [];
  await page.route("https://exposure.test/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/alpha/diagnostics") return route.fulfill({ json: { valid: true, diagnostics: [] } });
    if (path === "/api/research-runs") {
      submissions.push(route.request().postDataJSON());
      return route.fulfill({ status: 202, json: { id: "run_rules" } });
    }
    return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
  });
  const mount = async () => {
    await page.goto("https://exposure.test/?rules");
    await page.addStyleTag({ content: styles });
    await page.addScriptTag({ content: script });
  };
  await mount();
  await expect(page.getByLabel("Alpha formula", { exact: true })).not.toBeVisible();
  await expect(page.getByRole("textbox", { name: "Python source", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Run backtest", exact: true }).click();
  const formula = page.getByRole("textbox", { name: "Alpha formula", exact: true });
  await expect(formula).toBeVisible();
  await expect(formula).toBeFocused();
  expect(submissions).toHaveLength(0);
  await formula.fill("close / lag(close, 0) - 1");
  await page.getByRole("button", { name: "Run backtest", exact: true }).click();
  await expect(formula).toBeFocused();
  expect(submissions).toHaveLength(0);
  await formula.fill("close / lag(close, 20) - 1");
  await page.getByRole("tab", { name: /Portfolio/ }).click();
  const allocation = page.getByLabel("Total stock exposure (%)", { exact: true });
  await allocation.fill("150");
  await expect(allocation).toHaveValue("150");
  await page.getByRole("button", { name: "Run backtest", exact: true }).click();
  await expect(allocation).toBeFocused();
  expect(submissions).toHaveLength(0);
  await allocation.fill("60");
  await page.getByRole("tab", { name: /Risk/ }).click();
  await page.getByRole("switch", { name: "Stop loss", exact: true }).check();
  await page.getByLabel("Stop loss (%)", { exact: true }).fill("10");
  await expect(page.getByRole("button", { name: "Strategy summary", exact: true })).toHaveCount(0);
  await mount();
  await page.getByRole("tab", { name: /Signals/ }).click();
  await expect(formula).toHaveText("close / lag(close, 20) - 1");
  await page.getByRole("tab", { name: /Portfolio/ }).click();
  await expect(allocation).toHaveValue("60");
  await page.getByRole("tab", { name: /Risk/ }).click();
  await expect(page.getByLabel("Stop loss (%)", { exact: true })).toHaveValue("10");
  await page.getByRole("button", { name: "简体中文", exact: true }).click();
  await expect(page.getByRole("button", { name: "返回类型选择", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "策略摘要", exact: true })).toHaveCount(0);
  await page.screenshot({ path: test.info().outputPath("strategy-rules-zh.png"), fullPage: true });
  await page.getByRole("button", { name: "运行回测", exact: true }).click();
  await expect.poll(() => submissions.length).toBe(1);
  expect(submissions[0]).toMatchObject({
    strategy_mode: "framework", formula: "close / lag(close, 20) - 1",
    holdings_count: 10, selection_every_sessions: 5, exposure_expression: "0.6",
    modules: { risk_management: { kind: "builtin_risk/v1", stop_loss_threshold: 0.1 } },
  });
  expect(submissions[0]).not.toHaveProperty("program");
});
