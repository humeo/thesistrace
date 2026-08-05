import { defineConfig } from "@playwright/test";

const webPort = process.env.THESISTRACE_CORE_SHELL_PORT ?? "5274";
const baseURL = `http://127.0.0.1:${webPort}`;

export default defineConfig({
  testDir: "./e2e-core",
  workers: 1,
  use: { baseURL },
  webServer: [
    {
      command: `THESISTRACE_FIXTURE_AVAILABILITY_SEQUENCE=1,2,3 concurrently -k -n api,worker "../.venv/bin/thesistrace-api --port 8101" "../.venv/bin/thesistrace-worker"`,
      url: "http://127.0.0.1:8101/api/data",
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: `THESISTRACE_API_PORT=8101 vite --host 127.0.0.1 --port ${webPort}`,
      url: `${baseURL}/data`,
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
});
