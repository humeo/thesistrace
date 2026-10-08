import { expect, test, type Page } from "@playwright/test";
import { buildProductFixture } from "./build-product-fixture";

let script: string;
let styles: string;
const draftKey = "thesistrace.research-draft.exposure-test.folder_default";
const source = "def decide(data, account, state):\n    return None";

test.beforeAll(async () => {
  test.setTimeout(120_000);
  ({ script, styles } = await buildProductFixture(new URL("./fixtures/selection-exposure.tsx", import.meta.url), "DirectAuthoringFixture"));
});

async function mountDirect(page: Page) {
  await page.goto("https://exposure.test/");
  await page.addStyleTag({ content: styles });
  await page.addScriptTag({ content: script });
  await page.getByRole("radio", { name: "Python authoring", exact: true }).click();
}

test("Direct source survives checking and submission failures, with one pending request and safe retry", async ({ page }) => {
  const commands: Record<string, unknown>[] = [];
  let finish!: () => void;
  const pending = new Promise<void>(resolve => { finish = resolve; });
  await page.route("https://exposure.test/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/alpha/diagnostics") return route.fulfill({ json: { valid: true, diagnostics: [] } });
    if (path === "/api/research/diagnostics") return route.fulfill({ status: 503 });
    if (path === "/api/research-runs") {
      commands.push(route.request().postDataJSON());
      if (commands.length === 1) return route.fulfill({ status: 503 });
      if (commands.length === 2) {
        await pending;
        return route.fulfill({ status: 422, json: { issues: [{ code: "STRATEGY_PROGRAM_INVALID",
          field: "program.source", severity: "error", message: "program line 2: invalid strategy output", range: null,
          details: { kind: "strategy_program", error_type: "ValueError", line: 2 } }] } });
      }
      return route.fulfill({ status: 202, json: { id: "run_direct_retry" } });
    }
    return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
  });
  await mountDirect(page);
  const editor = page.locator("#python-source");
  await editor.fill(source);
  await page.getByRole("button", { name: "Check configuration", exact: true }).click();
  await expect(page.getByText("Configuration check is unavailable. Try again.")).toBeVisible();
  await expect(editor).toHaveText(source, { useInnerText: true });
  await page.getByRole("button", { name: "Run backtest", exact: true }).click();
  await expect(page.getByRole("list", { name: "Run issues" })).toContainText("Research Run request failed. Please try again.");
  await expect(editor).toHaveText(source, { useInnerText: true });
  await page.getByRole("button", { name: "Run backtest", exact: true }).evaluate(button => {
    (button as HTMLButtonElement).click();
    (button as HTMLButtonElement).click();
  });
  await expect.poll(() => commands.length).toBe(2);
  await expect(page.getByRole("button", { name: "New research", exact: true })).toBeDisabled();
  finish();
  await expect(editor).toHaveAttribute("aria-invalid", "true");
  await expect(editor).toHaveAccessibleDescription(/line 2/);
  expect(commands[1].request_id).toBe(commands[0].request_id);

  await editor.press("ControlOrMeta+End");
  await page.keyboard.insertText("\n# revised");
  await editor.press("Home");
  await editor.press("Shift+End");
  await page.getByRole("button", { name: "简体中文", exact: true }).dispatchEvent("click");
  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(editor).toBeFocused();
  await expect.poll(() => editor.evaluate(() => window.getSelection()?.toString())).toBe("# revised");
  await page.getByRole("button", { name: "English", exact: true }).dispatchEvent("click");
  await page.getByRole("radio", { name: "Modular authoring", exact: true }).click();
  await expect(editor).not.toBeVisible();
  await page.getByRole("radio", { name: "Python authoring", exact: true }).click();
  await editor.focus();
  await expect.poll(() => editor.evaluate(() => window.getSelection()?.toString())).toBe("# revised");
  await page.keyboard.insertText("# fixed");
  await editor.press("ControlOrMeta+z");
  await expect(editor).toHaveText(`${source}\n# revised`, { useInnerText: true });
  await editor.press("ControlOrMeta+z");
  await expect(editor).toHaveText(source, { useInnerText: true });
  await editor.press("ControlOrMeta+Shift+z");
  await expect(editor).toHaveText(`${source}\n# revised`, { useInnerText: true });
  await expect(editor).toHaveAttribute("aria-invalid", "false");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: test.info().outputPath("direct-recovery-desktop.png"), fullPage: true });
  await page.getByRole("button", { name: "Run backtest", exact: true }).click();
  await expect(page).toHaveURL("https://exposure.test/research-runs/run_direct_retry");
  expect(commands).toHaveLength(3);
  expect(commands[2].request_id).not.toBe(commands[0].request_id);
  expect(commands[2]).toMatchObject({ strategy_mode: "direct", program: {
    source: `${source}\n# revised`,
  } });
  expect(commands[2]).not.toHaveProperty("modules");
});

test("Direct storage failure keeps editable source, reports unsaved work and blocks admission", async ({ page }) => {
  let admissions = 0;
  await page.route("https://exposure.test/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/alpha/diagnostics") return route.fulfill({ json: { valid: true, diagnostics: [] } });
    if (path === "/api/research-runs") { admissions++; return route.fulfill({ status: 202, json: { id: "unexpected" } }); }
    return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
  });
  await mountDirect(page);
  await page.evaluate(() => {
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (key.startsWith("thesistrace.research-draft.")) throw new DOMException("Quota exceeded", "QuotaExceededError");
      return original.call(this, key, value);
    };
  });
  const editor = page.locator("#python-source");
  await editor.fill(source);
  await expect(page.getByRole("alert")).toContainText("could not be retained");
  await expect(page.getByText("Draft saved in this browser", { exact: true })).not.toBeVisible();
  await page.getByRole("button", { name: "Run backtest", exact: true }).click();
  expect(admissions).toBe(0);
  await expect(editor).toHaveText(source, { useInnerText: true });
  const storedSource = await page.evaluate(key => JSON.parse(localStorage.getItem(key)!).programSource, draftKey);
  expect(storedSource).not.toBe(source);
});

test("Python editor opens current writing reference without changing source", async ({ page }) => {
  const reads: string[] = [];
  await page.route("https://exposure.test/**", route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/authoring-reference")) {
      reads.push(url.searchParams.get("topic") ?? "");
      return route.fulfill({ json: {
        topic: "python_sdk", title: "Python SDK", found: true,
        overview: ["compute(data, state) returns multi-date Targets or Values."],
        symbols: [{ symbol: "BatchData.history", description: "Read a block." }], entry: null,
      } });
    }
    return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
  });
  await mountDirect(page);
  const editor = page.locator("#python-source");
  await editor.fill(source);
  await page.getByRole("button", { name: "Writing reference", exact: true }).click();
  const reference = page.getByRole("dialog", { name: "Writing reference", exact: true });
  await expect(reference.getByText("compute(data, state) returns multi-date Targets or Values.")).toBeVisible();
  await expect(reference.getByRole("combobox", { name: "Reference member" })).toBeVisible();
  expect(reads).toEqual(["python_sdk"]);
  await page.keyboard.press("Escape");
  await expect(reference).toHaveCount(0);
  await expect(editor).toHaveText(source, { useInnerText: true });
});
