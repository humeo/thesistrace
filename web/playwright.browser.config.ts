import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./browser",
  workers: 1,
  outputDir: "../.local/browser-tests/results",
  reporter: [["line"], ["html", { open: "never", outputFolder: "../.local/browser-tests/report", noSnippets: true }]],
  use: { screenshot: "only-on-failure", trace: "retain-on-failure" },
});
