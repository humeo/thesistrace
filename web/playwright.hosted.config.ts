import { defineConfig } from "@playwright/test";

const baseURL = process.env.THESISTRACE_HOSTED_ORIGIN;
if (!baseURL) {
  throw new Error("THESISTRACE_HOSTED_ORIGIN is required");
}

export default defineConfig({
  testDir: "./e2e-hosted",
  testMatch: "hosted-acceptance.spec.ts",
  workers: 1,
  timeout: 180_000,
  use: {
    baseURL,
    ignoreHTTPSErrors: process.env.THESISTRACE_SMOKE_INSECURE_TLS === "1",
    viewport: { width: 1440, height: 1000 },
  },
});
