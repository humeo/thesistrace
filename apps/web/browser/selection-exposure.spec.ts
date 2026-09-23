import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { build } from "vite";

let script: string;
const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

for (const width of [1280, 390]) {
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
            message: "portfolio_construction, line 1: SyntaxError: invalid syntax", severity: "error", range: null }],
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
    await page.getByRole("combobox", { name: "Alpha / Signals module", exact: true }).selectOption("python");
    await page.getByRole("combobox", { name: "Portfolio Construction module", exact: true }).selectOption("python");
    const alpha = page.getByRole("region", { name: "Alpha / Signals module", exact: true });
    const portfolio = page.getByRole("region", { name: "Portfolio Construction module", exact: true });
    await expect(alpha.getByLabel("Python source", { exact: true })).toContainText("momentum_signals");
    await expect(portfolio.getByLabel("Python source", { exact: true })).toContainText("better_signal_candidate");
    await expect(page.getByLabel("Alpha formula", { exact: true })).toHaveCount(0);
    await expect(page.getByLabel("Holdings count", { exact: true })).toHaveCount(0);
    await portfolio.getByLabel("Parameters (JSON)", { exact: true }).fill("{");
    await page.getByRole("button", { name: "Run backtest", exact: true }).click();
    await expect(portfolio.getByLabel("Parameters (JSON)", { exact: true })).toBeFocused();
    expect(submissions).toHaveLength(0);
    await mount();
    await expect(portfolio.getByLabel("Parameters (JSON)", { exact: true })).toHaveValue("{");
    await portfolio.getByLabel("Parameters (JSON)", { exact: true }).fill('{"improvement": 0.04}');
    await page.getByRole("button", { name: "Check configuration" }).click();
    await expect(portfolio.locator("#portfolio_construction-python-source-error")).toContainText("line 1");
    await expect(alpha.getByLabel("Python source", { exact: true })).not.toHaveAttribute("aria-invalid", "true");
    await portfolio.getByLabel("Python source", { exact: true }).fill("def decide(context, state, parameters):\n    return {'output': None, 'state': state}\n");
    await page.getByRole("button", { name: "Check configuration" }).click();
    await expect(page.getByText("Configuration is valid.", { exact: false })).toBeVisible();
    expect(checks[1]).toMatchObject({ strategy_mode: "framework", modules: {
      alpha: { kind: "python", program: { data_requirements: { field_ids: ["price.close.adjusted"], history_sessions: 6 } } },
      portfolio_construction: { kind: "python", program: { parameters: { improvement: 0.04 } } },
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

for (const width of [1280, 390]) {
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
            message: "program abcdef123456, line 1: SyntaxError: invalid syntax", severity: "error", range: null }],
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
    await page.getByLabel("Strategy mode", { exact: true }).selectOption("direct");
    await expect(page.getByLabel("Python source", { exact: true })).toContainText("def decide");
    await expect(page.getByLabel("Alpha formula", { exact: true })).toHaveCount(0);
    await expect(page.getByLabel("Holdings count", { exact: true })).toHaveCount(0);
    await page.getByLabel("Parameters (JSON)", { exact: true }).fill("{");
    await page.getByRole("button", { name: "Run backtest", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("JSON");
    await expect(page.getByLabel("Parameters (JSON)", { exact: true })).toBeFocused();
    await page.getByLabel("Python source", { exact: true }).focus();
    await expect(page.locator("#python-parameters-error")).toContainText("JSON");
    expect(submissions).toHaveLength(0);
    await mount();
    await expect(page.getByLabel("Parameters (JSON)", { exact: true })).toHaveValue("{");
    await page.getByLabel("Parameters (JSON)", { exact: true }).fill('{"improvement": 0.03}');
    await page.getByLabel("Python source", { exact: true }).fill("def decide(:");
    await page.getByRole("button", { name: "Check configuration" }).click();
    await expect(page.getByLabel("Configuration issues")).toContainText("line 1");
    await expect(page.locator("#python-source-error")).toContainText("line 1");
    const source = "def decide(context, state, parameters):\n    return {'output': None, 'state': state}\n";
    await page.getByLabel("Python source", { exact: true }).fill(source);
    await expect(page.getByLabel("Configuration issues")).not.toBeVisible();
    await page.getByRole("button", { name: "Check configuration" }).click();
    await expect(page.getByText("Configuration is valid.", { exact: false })).toBeVisible();
    expect(checks[1]).toMatchObject({ strategy_mode: "direct", program: {
      source, parameters: { improvement: 0.03 },
      data_requirements: { field_ids: ["price.close.adjusted"], history_sessions: 6 },
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

test("switching back to built-in Framework removes the Python definition", async ({ page }) => {
  await page.route("https://exposure.test/**", route => route.fulfill({
    contentType: "text/html", body: '<div id="root"></div>',
  }));
  await page.goto("https://exposure.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  const mode = page.getByLabel("Strategy mode", { exact: true });
  await mode.selectOption("direct");
  await page.getByLabel("Python source", { exact: true }).fill("private draft");
  await mode.selectOption("framework");
  await expect(page.getByLabel("Python source", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("Alpha formula", { exact: true })).toBeVisible();
  const draft = await page.evaluate(() => JSON.parse(localStorage.getItem("thesistrace.research-draft.exposure-test.folder_default")!));
  expect(draft.programSource).toBe("");
  expect(draft.programParameters).toBe("");
  expect(draft.programFields).toBe("");
});
test.beforeAll(async () => {
  const result = await build({
    configFile: false, logLevel: "silent", esbuild: { jsx: "automatic" },
    define: { "process.env.NODE_ENV": JSON.stringify("production") },
    build: { write: false, minify: false, lib: {
      entry: fileURLToPath(new URL("./fixtures/selection-exposure.tsx", import.meta.url)),
      formats: ["iife"], name: "SelectionExposureFixture",
    } },
  });
  if ("on" in result) throw new Error("Expected one-off build");
  const chunk = (Array.isArray(result) ? result : [result]).flatMap(bundle => bundle.output)
    .find(output => output.type === "chunk" && output.isEntry);
  if (chunk?.type !== "chunk") throw new Error("Missing component bundle");
  script = chunk.code;
});

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
    return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
  });
  const mount = async () => {
    await page.goto("https://exposure.test/");
    await page.addStyleTag({ content: styles });
    await page.addScriptTag({ content: script });
  };
  await mount();
  await expect(page.getByText(/Framework · Decision modules\. Decide/)).toBeVisible();
  await expect(page.getByText(/Decide after the close; simulate trades at the next/)).toBeVisible();
  await page.getByRole("button", { name: "Run settings", exact: true }).click();
  await expect(page.getByLabel("Portfolio weighting", { exact: false })).toHaveValue("equal_weight");
  await page.getByLabel("Portfolio weighting", { exact: false }).selectOption(weighting);
  if (weighting === "inverse_volatility") {
    await expect(page.getByLabel("Volatility window", { exact: false })).toHaveValue("20");
    await page.getByLabel("Volatility window", { exact: false }).fill("10");
  }
  await expect(page.getByLabel("Exposure expression", { exact: true })).toHaveText("1");
  await expect(page.getByRole("radio", { name: "Fixed percentage", exact: true })).toHaveCount(0);
  await page.getByLabel("Exposure expression", { exact: true }).fill("0.7");
  await expect(page.getByLabel("Exposure expression", { exact: true })).toHaveText("0.7");
  await mount();
  await page.getByRole("button", { name: "Run settings", exact: true }).click();
  await expect(page.getByLabel("Portfolio weighting", { exact: false })).toHaveValue(weighting);
  if (weighting === "inverse_volatility") {
    await expect(page.getByLabel("Volatility window", { exact: false })).toHaveValue("10");
  }
  await expect(page.getByLabel("Exposure expression", { exact: true })).toHaveText("0.7");
  await page.getByLabel("Exposure expression", { exact: true }).fill("7 / 10");
  await expect(page.getByLabel("Fixed exposure (%)", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Run settings", exact: true }).click();
  await page.getByRole("button", { name: "Check configuration" }).click();
  await expect(page.getByText("Configuration is valid.", { exact: false })).toBeVisible();
  expect(diagnostics).toHaveLength(1);
  expect(diagnostics[0]).toMatchObject({ exposure_expression: "7 / 10", weighting, volatility_window: weighting === "inverse_volatility" ? 10 : 20, selection_every_sessions: 5, initial_cash_cny: "100000" });
  expect(diagnostics[0]).not.toHaveProperty("request_id");
  expect(submissions).toHaveLength(0);
  await page.getByRole("button", { name: "Run settings", exact: true }).click();
  await page.getByLabel("Exposure expression", { exact: true }).fill("0");
  await expect(page.getByText("Configuration is valid.", { exact: false })).not.toBeVisible();
  await expect(page.getByLabel("Exposure expression", { exact: true })).toHaveText("0");
  await expect.poll(() => localContexts.includes("exposure")).toBe(true);
  await page.screenshot({ path: `../../.local/browser-tests/selection-${weighting}.png`, fullPage: true });
  await page.getByRole("button", { name: "Run settings", exact: true }).click();
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
          message: "Exposure must be between zero and one.", severity: "error", range: null }],
      } });
      if (checks === 2) return route.fulfill({ status: 503, body: "Unavailable" });
      return route.fulfill({ json: { valid: true, issues: [] } });
    }
    return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
  });
  await page.goto("https://exposure.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await page.getByRole("button", { name: "Run settings", exact: true }).click();
  await page.getByLabel("Exposure expression", { exact: true }).fill("1 + 0.1");
  await page.getByRole("button", { name: "Run settings", exact: true }).click();
  const check = page.getByRole("button", { name: "Check configuration" });
  await check.click();
  await expect(page.getByLabel("Configuration issues")).toContainText("exposure_expression");
  await page.getByRole("button", { name: "Run settings", exact: true }).click();
  await page.getByLabel("Exposure expression", { exact: true }).fill("0.3");
  await page.getByRole("button", { name: "Run settings", exact: true }).click();
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
    return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
  });
  const mount = async () => {
    await page.goto("https://exposure.test/");
    await page.addStyleTag({ content: styles });
    await page.addScriptTag({ content: script });
  };
  await mount();
  await page.getByRole("button", { name: "Run settings", exact: true }).click();
  const editor = page.getByLabel("Exposure expression", { exact: true });
  await editor.fill("");
  await editor.press("Control+Space");
  await expect(page.getByRole("listbox", { name: "Completions" }).getByRole("option").filter({ hasText: "universe_return" })).toBeVisible();
  await expect(page.getByRole("listbox", { name: "Completions" }).getByRole("option").filter({ hasText: "rank" })).toHaveCount(0);
  await expect(page.getByRole("listbox", { name: "Completions" }).getByRole("option").filter({ hasText: "close" })).toHaveCount(0);
  await editor.press("Escape");
  const expression = "if_else(universe_return() > 0, 1, 0.3)";
  await editor.fill(expression);
  await expect(page.getByLabel("Fixed exposure (%)", { exact: true })).toHaveCount(0);
  await mount();
  await page.getByRole("button", { name: "Run settings", exact: true }).click();
  await expect(page.getByLabel("Exposure expression", { exact: true })).toHaveText(expression);
  await page.getByRole("button", { name: "Run settings", exact: true }).click();
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
      return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    });
    await page.goto("https://exposure.test/");
    await page.addStyleTag({ content: styles });
    await page.addScriptTag({ content: script });
    await page.getByRole("button", { name: "Run settings", exact: true }).click();
    const selector = page.getByLabel("Portfolio weighting", { exact: false });
    await selector.selectOption("inverse_volatility");
    await page.getByLabel("Volatility window", { exact: false }).fill("253");
    await page.getByRole("button", { name: "Run backtest", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("Volatility window");
    await selector.selectOption(weighting);
    await expect(page.getByLabel("Volatility window", { exact: false })).not.toBeVisible();
    await expect(page.getByRole("button", { name: "Check configuration" })).toBeEnabled();
    await page.getByRole("button", { name: "Run settings", exact: true }).click();
  await page.getByRole("button", { name: "Run backtest", exact: true }).click();
    await expect.poll(() => submissions.length).toBe(1);
    expect(submissions[0]).toMatchObject({ weighting, volatility_window: 20 });
  });
}

for (const width of [1280, 390]) {
  test(`Research workbench keeps settings compact and keyboard accessible at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 964 });
    await page.route("https://exposure.test/**", route => {
      if (new URL(route.request().url()).pathname === "/api/alpha/diagnostics") {
        return route.fulfill({ json: { valid: true, diagnostics: [] } });
      }
      return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    });
    await page.goto("https://exposure.test/");
    await page.addStyleTag({ content: styles });
    await page.addScriptTag({ content: script });
    const dialog = page.getByRole("region", { name: "Run settings", exact: true });
    const trigger = page.getByRole("button", { name: "Run settings", exact: true });
    await expect(dialog).not.toBeVisible();
    await expect(page.getByRole("button", { name: "Run backtest" })).toBeInViewport();
    const notes = page.getByLabel("Notes", { exact: true });
    await expect(notes).not.toBeVisible();
    const notesDisclosure = page.locator("summary").filter({ hasText: /^Notes$/ });
    await notesDisclosure.focus();
    await notesDisclosure.press("Enter");
    await expect(notes).toBeVisible();
    await trigger.click();
    await expect(dialog).toBeVisible();
    await expect(page.getByRole("tooltip")).toHaveCount(0);
    const help = page.getByRole("button", { name: "Cash requirements" });
    await help.hover();
    await expect(page.getByRole("tooltip")).toContainText("two decimal places");
    await help.focus();
    await help.press("Escape");
    await expect(page.getByRole("tooltip")).toHaveCount(0);
    await page.getByLabel("Initial cash (CNY)", { exact: true }).focus();
    await help.click();
    await expect(page.getByRole("tooltip")).toBeVisible();

    await page.getByLabel("Initial cash (CNY)", { exact: true }).focus();
    await page.setViewportSize({ width, height: 500 });
    for (const name of ["Weighting help", "Exposure formula help"]) {
      const exampleHelp = page.getByRole("button", { name, exact: true });
      await exampleHelp.evaluate((element) => element.scrollIntoView({ block: "center" }));
      await exampleHelp.click();
      const tooltip = page.getByRole("tooltip");
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
    await trigger.click();
    await expect(dialog).not.toBeVisible();
    await expect(trigger).toBeFocused();
    await trigger.click();
    await expect(page.getByLabel("Initial cash (CNY)", { exact: false })).toHaveValue("250000");
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByRole("textbox", { name: "Alpha formula", exact: true })).toBeVisible();
    await trigger.click();
    await page.getByRole("radio", { name: "Factor Evaluation" }).check();
    await expect(page.getByRole("button", { name: "Run evaluation" })).toBeVisible();
    await trigger.click();
    await expect(page.getByLabel("Portfolio weighting", { exact: false })).not.toBeVisible();
    await page.getByRole("button", { name: "Run settings", exact: true }).click();
    await page.getByLabel("Notes", { exact: true }).fill("Compare the signal across market regimes.");
    const browse = page.getByRole("button", { name: "Browse fields", exact: true });
    await browse.click();
    const fields = page.getByRole("complementary", { name: "Field browser" });
    await expect(fields).toBeVisible();
    await expect(fields.getByRole("searchbox", { name: "Search fields" })).toBeFocused();
    await fields.getByRole("searchbox").fill("close");
    await expect(fields.getByRole("button", { name: "复权收盘价" })).toBeVisible();
    await expect(fields.locator("#data-field-detail")).toContainText("Adjusted Close");
    await fields.getByRole("searchbox").fill("not_a_field");
    await expect(fields.getByText("No fields match these filters.")).toBeVisible();
    await fields.getByRole("button", { name: "Clear search" }).click();
    await fields.getByRole("searchbox").press("Escape");
    await expect(fields).not.toBeVisible();
    await expect(browse).toBeFocused();
    await expect(page.getByRole("textbox", { name: "Alpha formula", exact: true })).toHaveText("close");
    await browse.click();
    await page.getByRole("button", { name: "Close field browser" }).click();
    await expect(fields).not.toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: `../../.local/browser-tests/research-workbench-${width}.png`, fullPage: true });
  });
}

for (const width of [1280, 390]) {
  test(`Missing required settings are reachable from Run at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 964 });
    let submissions = 0;
    await page.route("https://exposure.test/**", route => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/alpha/diagnostics") return route.fulfill({ json: { valid: true, diagnostics: [] } });
      if (path === "/api/research-runs") { submissions++; return route.fulfill({ status: 202, json: { id: "run_valid" } }); }
      return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
    });
    await page.goto("https://exposure.test/");
    await page.addStyleTag({ content: styles });
    await page.addScriptTag({ content: script });
    await expect(page.getByLabel("Holdings count", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Selection interval (trading days)", { exact: true })).toHaveValue("5");
    await page.getByRole("button", { name: "Run settings", exact: true }).click();
    await page.getByLabel("Initial cash (CNY)", { exact: true }).fill("");
    await page.getByRole("button", { name: "Run settings", exact: true }).click();
    await page.getByRole("button", { name: "Run backtest", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("Initial cash");
    await expect(page.getByLabel("Initial cash (CNY)", { exact: true })).toBeFocused();
    expect(submissions).toBe(0);
    await page.getByLabel("Initial cash (CNY)", { exact: true }).fill("100000");
    await page.getByLabel("Exposure expression", { exact: true }).fill("1.1");
    await page.getByRole("button", { name: "Run backtest", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("between 0 and 1");
    await expect(page.getByLabel("Exposure expression", { exact: true })).toBeFocused();
    expect(submissions).toBe(0);
    const expression = "if_else(universe_return() > 0, 1, 0.3)";
    await page.getByLabel("Exposure expression", { exact: true }).fill(expression);
    await page.getByRole("button", { name: "Run settings", exact: true }).click();
    await page.getByLabel("Alpha formula", { exact: true }).fill("");
    await page.getByRole("button", { name: "Run backtest", exact: true }).click();
    await expect(page.getByLabel("Alpha formula", { exact: true })).toBeFocused();
    expect(submissions).toBe(0);
    await page.getByLabel("Alpha formula", { exact: true }).fill("close");
    await page.getByRole("button", { name: "Run backtest", exact: true }).click();
    await expect.poll(() => submissions).toBe(1);
  });
}
