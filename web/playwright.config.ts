import { defineConfig } from "@playwright/test";

const webPort = process.env.THESISTRACE_WEB_PORT ?? "5273";
const baseURL = `http://127.0.0.1:${webPort}`;

export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  use: {
    baseURL,
  },
  webServer: {
    command: "bun run dev:test",
    url: baseURL,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
