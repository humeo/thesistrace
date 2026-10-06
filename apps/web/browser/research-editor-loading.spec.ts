import { expect, test } from "./workbench-fixture";

test("Research loads editing libraries only when their authoring mode opens", async ({ page, bundle }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  const scripts = new Set<string>();
  page.on("request", request => {
    if (request.resourceType() === "script") scripts.add(new URL(request.url()).pathname.slice(1));
  });
  const loadedModules = () => [...scripts].flatMap(file => bundle.get(file)?.modules ?? []);
  await page.goto("/research");
  await expect(page.getByRole("heading", { name: "Choose a research type", exact: true })).toBeVisible();
  await testInfo.attach("research-entry-bytes", { body: JSON.stringify({
    javascriptBytes: [...scripts].reduce((total, file) => total + Buffer.byteLength(bundle.get(file)?.body ?? ""), 0),
  }), contentType: "application/json" });
  expect(loadedModules().filter(id => id.includes("/@codemirror/"))).toEqual([]);

  await page.getByRole("button", { name: "Factor Evaluation", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Alpha formula", exact: true })).toBeVisible();
  expect(loadedModules().some(id => id.includes("/@codemirror/view/"))).toBe(true);
  expect(loadedModules().filter(id => id.includes("/@codemirror/lang-python/"))).toEqual([]);
  await page.getByRole("button", { name: "Back to research types", exact: true }).click();
  await page.getByRole("button", { name: "Strategy Backtest", exact: true }).click();
  await page.getByRole("radio", { name: "Python authoring", exact: true }).click();
  const source = page.getByRole("textbox", { name: "Python source", exact: true });
  await expect(source).toBeVisible();
  expect(loadedModules().some(id => id.includes("/@codemirror/lang-python/"))).toBe(true);
});
