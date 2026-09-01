import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

const webPort = Number(process.env.THESISTRACE_WEB_PORT ?? "5173");
const apiPort = Number(process.env.THESISTRACE_API_PORT ?? "8000");
const apiOrigin = process.env.THESISTRACE_API_ORIGIN ?? `http://127.0.0.1:${apiPort}`;
const agentOrigin = process.env.THESISTRACE_AGENT_ORIGIN ?? "http://127.0.0.1:8400";

export default defineConfig({
  plugins: [
    react(),
    {
      name: "reject-removed-web-entries",
      configureServer(server) {
        server.middlewares.use((request, response, next) => {
          const pathname = new URL(request.url ?? "/", "http://localhost").pathname;
          if (pathname === "/core.html") {
            response.statusCode = 404;
            response.end();
            return;
          }
          next();
        });
      },
    },
  ],
  build: {
    rollupOptions: {
      input: {
        product: fileURLToPath(new URL("./index.html", import.meta.url)),
      },
    },
  },
  server: {
    port: webPort,
    proxy: {
      "/api/agent": agentOrigin,
      "/api": apiOrigin,
    },
  },
});
