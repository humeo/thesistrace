import { defineConfig, mergeConfig } from "vitest/config";
import viteConfig from "./vite.config";

export default mergeConfig(viteConfig, defineConfig({
  test: { server: { deps: { inline: [/@copilotkit\/react-core/] } }, include: ["src/**/*.test.ts", "src/**/*.test.tsx"] },
}));
