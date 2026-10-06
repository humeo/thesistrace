import { expect, test as base } from "@playwright/test";
import { build } from "vite";
import { fileURLToPath } from "node:url";
import { serveBrandAssets } from "./brand-assets";
import { workbenchData } from "./fixtures/workbench-data";
export { workbenchData } from "./fixtures/workbench-data";

const researcherId = "00000000-0000-4000-8000-000000000001";

// Use the actual entry point: route changes, Auth boundary and CSS are production code.
// Only HTTP facts are fixtures. Each Playwright context owns its mutable state.
export const test = base.extend<{ workbench: void }, { bundle: Map<string, { body: string | Buffer; contentType: string }> }>({
  baseURL: "https://workbench.fixture",
  bundle: [async ({}, use) => {
    const result = await build({
      root: fileURLToPath(new URL("../", import.meta.url)),
      configFile: fileURLToPath(new URL("../vite.config.ts", import.meta.url)),
      logLevel: "error", build: { write: false },
    });
    if ("on" in result) throw new Error("one-off product build required");
    const output = (Array.isArray(result) ? result : [result]).flatMap(item => item.output);
    const files = new Map(output.map(item => [item.fileName, {
      body: item.type === "chunk" ? item.code : typeof item.source === "string" ? item.source : Buffer.from(item.source),
      contentType: item.fileName.endsWith(".js") ? "text/javascript" : item.fileName.endsWith(".css") ? "text/css" : "text/html",
    }]));
    if (!files.has("index.html")) throw new Error("product HTML entry missing");
    await use(files);
  }, { scope: "worker", timeout: 60_000 }],
  workbench: [async ({ page, context, bundle }, use) => {
    const unexpected: string[] = [];
    page.on("pageerror", error => unexpected.push(error.message));
    await context.route("https://workbench.fixture/**", async route => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      const asset = bundle.get(path.slice(1));
      if (asset) return route.fulfill(asset);
      if (request.resourceType() === "document") return route.fulfill(bundle.get("index.html")!);
      if (path === "/api/auth/get-session") return route.fulfill({ json: {
        session: { id: "00000000-0000-4000-8000-000000000002" },
        user: { id: researcherId, email: "browser@example.test", name: "Browser", active: true },
      } });
      if (path === "/api/auth/operator/capability") return route.fulfill({ status: 404, body: "" });
      if (path === "/api/researcher/bootstrap") return route.fulfill({ json: {
        researcher_id: researcherId, system_folders: { default: "folder_default", batch_research: "folder_batch_research" },
      } });
      if (path === "/api/agent/sessions") return route.fulfill({ json: { sessions: [], next_cursor: null } });
      if (path === "/api/data") return route.fulfill({ json: workbenchData });
      if (path === "/api/research-folders") return route.fulfill({ json: {
        items: [{ id: "folder_default", name: "Default", is_default: true, created_at: "2026-08-01T00:00:00Z" }], next_cursor: null,
      } });
      if (path === "/api/alpha/diagnostics" || path === "/api/research/diagnostics") return route.fulfill({ json: { valid: true, diagnostics: [] } });
      if (path === "/api/daily-tracks/track_cafebabefeed1234") return route.fulfill({ status: 404, json: { code: "NOT_FOUND" } });
      unexpected.push(`${request.method()} ${path}`);
      await route.fulfill({ status: 500, json: { code: "UNEXPECTED_FIXTURE_REQUEST" } });
    });
    await serveBrandAssets(page);
    await use();
    expect(unexpected).toEqual([]);
  }, { auto: true }],
});
export { expect };
