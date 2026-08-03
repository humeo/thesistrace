import { defineConfig } from "@playwright/test";

const webPort = process.env.THESISTRACE_CORE_SHELL_PORT ?? "5274";
const baseURL = `http://127.0.0.1:${webPort}`;

export default defineConfig({
  testDir: "./e2e-core",
  workers: 1,
  use: { baseURL },
  webServer: {
    command: `concurrently -k -n api,worker,web "../.venv/bin/thesistrace-core-api --port 8101" "../.venv/bin/thesistrace-core-worker" "THESISTRACE_API_PORT=8101 vite --host 127.0.0.1 --port ${webPort}"`,
    url: `${baseURL}/core.html`,
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
