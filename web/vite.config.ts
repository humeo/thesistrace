import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

const webPort = Number(process.env.THESISTRACE_WEB_PORT ?? "5173");
const apiPort = Number(process.env.THESISTRACE_API_PORT ?? "8000");

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      input: {
        core: fileURLToPath(new URL("./core.html", import.meta.url)),
        product: fileURLToPath(new URL("./index.html", import.meta.url)),
      },
    },
  },
  server: {
    port: webPort,
    proxy: {
      "/api": `http://127.0.0.1:${apiPort}`,
    },
  },
});
