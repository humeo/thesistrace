import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";
import { build, type PluginOption } from "vite";

/** Build fixture JavaScript and CSS through the product's Tailwind pipeline. */
export async function buildProductFixture(entry: URL, name: string, fixturePlugins: PluginOption[] = []): Promise<{ script: string; styles: string }> {
  const result = await build({
    configFile: false,
    plugins: [...fixturePlugins, tailwindcss()],
    resolve: { alias: { "@": fileURLToPath(new URL("../src", import.meta.url)) } },
    logLevel: "silent",
    // A preceding Vite dev-server test can leave NODE_ENV=development in this worker.
    // Keep generated JSX consistent with the production React runtime defined below.
    esbuild: { jsx: "automatic", jsxDev: false },
    define: { "process.env.NODE_ENV": JSON.stringify("production") },
    build: {
      write: false,
      minify: false,
      cssCodeSplit: false,
      lib: { entry: fileURLToPath(entry), formats: ["iife"], name },
    },
  });
  if ("on" in result) throw new Error("one-off build required");
  const output = (Array.isArray(result) ? result : [result]).flatMap(bundle => bundle.output);
  const entryChunk = output.find(item => item.type === "chunk" && item.isEntry);
  const cssAsset = output.find(item => item.type === "asset" && item.fileName.endsWith(".css"));
  if (entryChunk?.type !== "chunk" || cssAsset?.type !== "asset") {
    throw new Error("fixture JavaScript or stylesheet missing");
  }
  return {
    script: entryChunk.code,
    styles: typeof cssAsset.source === "string" ? cssAsset.source : new TextDecoder().decode(cssAsset.source),
  };
}

/** Preserve the library's lazy chunks instead of inlining every Markdown grammar. */
export async function buildModuleProductFixture(entry: URL) {
  const result = await build({
    configFile: false, plugins: [tailwindcss()], logLevel: "silent",
    resolve: { alias: { "@": fileURLToPath(new URL("../src", import.meta.url)) } },
    esbuild: { jsx: "automatic", jsxDev: false },
    define: { "process.env.NODE_ENV": JSON.stringify("production") },
    build: { write: false, minify: false, rollupOptions: { input: fileURLToPath(entry) } },
  });
  if ("on" in result) throw new Error("one-off build required");
  const output = (Array.isArray(result) ? result : [result]).flatMap(bundle => bundle.output);
  const chunk = output.find(item => item.type === "chunk" && item.isEntry);
  if (!chunk) throw new Error("fixture entry missing");
  const files = new Map(output.map(item => [item.fileName, {
    body: item.type === "chunk" ? item.code : typeof item.source === "string" ? item.source : Buffer.from(item.source),
    contentType: item.fileName.endsWith(".js") ? "text/javascript" : item.fileName.endsWith(".css") ? "text/css" : "application/octet-stream",
  }]));
  const styles = output.filter(item => item.fileName.endsWith(".css")).map(item => `<link rel="stylesheet" href="/${item.fileName}">`).join("");
  files.set("index.html", { body: `<!doctype html><html><head><meta charset="utf-8">${styles}</head><body><div id="root"></div><script type="module" src="/${chunk.fileName}"></script></body></html>`, contentType: "text/html" });
  return files;
}
