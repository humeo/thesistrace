import { expect, test } from "@playwright/test";
import { buildProductFixture } from "./build-product-fixture";

let fixture: Awaited<ReturnType<typeof buildProductFixture>>;
test.beforeAll(async () => { fixture = await buildProductFixture(new URL("./fixtures/conditional-alpha.tsx", import.meta.url), "ConditionalAlphaFixture"); });


test("conditional Alpha editing preserves source and recognizes Boolean grammar", async ({ page }) => {
  await page.setContent('<div id="root"></div>');
  await page.addStyleTag({ content: fixture.styles });
  await page.addScriptTag({ content: fixture.script });
  const editor = page.locator('.cm-content');
  const formula = 'if_else(close > open and not (open == 0), close / open, 0)';
  await editor.fill(formula);
  await expect(page.getByLabel('Saved formula')).toHaveText(formula);
  await expect(page.getByLabel('Syntax errors')).toHaveText('0');
  await expect(page.locator('.cm-alpha-operator').filter({ hasText: 'and' })).toBeVisible();
  await editor.fill('if_else(close >= open or close != 0, close, open)');
  await expect(page.getByLabel('Syntax errors')).toHaveText('0');
});


test("common industry parameters are discoverable in the actual editor", async ({ page }) => {
  await page.setContent('<div id="root"></div>');
  await page.addStyleTag({ content: fixture.styles });
  await page.addScriptTag({ content: fixture.script });
  const editor = page.locator('.cm-content');
  await editor.fill('close * industry_return(801');
  await editor.press('Control+Space');
  const choice = page.getByRole('option').filter({ hasText: '801010' });
  await expect(choice).toBeVisible();
  await expect(choice).toContainText('Agriculture, forestry, livestock & fisheries');
  await choice.click();
  await editor.press('End');
  await editor.press(')');
  await expect(page.getByLabel('Saved formula')).toHaveText('close * industry_return(801010)');
  await expect(page.getByLabel('Syntax errors')).toHaveText('0');
});
