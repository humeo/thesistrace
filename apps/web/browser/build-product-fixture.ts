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
    esbuild: { jsx: "automatic" },
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
