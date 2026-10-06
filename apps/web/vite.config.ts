import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";

const webPort = Number(process.env.THESISTRACE_WEB_PORT ?? "5173");
const apiPort = Number(process.env.THESISTRACE_API_PORT ?? "8000");
const apiOrigin = process.env.THESISTRACE_API_ORIGIN ?? `http://127.0.0.1:${apiPort}`;
const agentOrigin = process.env.THESISTRACE_AGENT_ORIGIN ?? "http://127.0.0.1:8400";

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
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
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  build: {
    manifest: true,
    rollupOptions: {
      input: {
        product: fileURLToPath(new URL("./index.html", import.meta.url)),
      },
      output: {
        // Coalesce tiny icon chunks without pulling route-specific UI into every page.
        manualChunks(id) {
          if (
            id.includes("/@phosphor-icons/react/dist/csr/CaretLeft.es.js")
            || id.includes("/@phosphor-icons/react/dist/csr/CaretDown.es.js")
            || id.includes("/@phosphor-icons/react/dist/csr/MagnifyingGlass.es.js")
            || id.includes("/@phosphor-icons/react/dist/csr/Copy.es.js")
          ) return "icons-ui";
          return undefined;
        },
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
