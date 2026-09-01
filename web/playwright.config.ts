import { defineConfig } from "@playwright/test";

const baseURL = process.env.THESISTRACE_TEST_WEB_ORIGIN;
const evidenceDir = process.env.THESISTRACE_TEST_EVIDENCE_DIR;

if (!baseURL || !evidenceDir) {
  throw new Error(
    "Playwright requires THESISTRACE_TEST_WEB_ORIGIN and THESISTRACE_TEST_EVIDENCE_DIR",
  );
}

export default defineConfig({
  testDir: "./e2e-core",
  workers: 1,
  outputDir: `${evidenceDir}/playwright-results`,
  reporter: [
    ["line"],
    ["html", {
      noSnippets: true,
      open: "never",
      outputFolder: `${evidenceDir}/playwright-report`,
    }],
  ],
  use: {
    baseURL,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure",
  },
});
