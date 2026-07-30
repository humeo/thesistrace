import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const webPort = Number(process.env.THESISTRACE_WEB_PORT ?? "5173");
const apiPort = Number(process.env.THESISTRACE_API_PORT ?? "8000");

export default defineConfig({
  plugins: [react()],
  server: {
    port: webPort,
    proxy: {
      "/api": `http://127.0.0.1:${apiPort}`,
    },
  },
});
