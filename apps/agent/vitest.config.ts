import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // Bound parallel Mastra module loads and large-context fixtures on local hosts.
    maxWorkers: 4,
    exclude: ["src/**/*.integration.test.ts"],
    include: ["src/**/*.test.ts"],
  },
});
