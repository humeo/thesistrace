import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

// Bound the full product bundle, including the native chat and Markdown libraries.
const MAX_ASSET_COUNT = 500;
const MAX_ASSET_BYTES = 20 * 1024 * 1024;
const MAX_JAVASCRIPT_BYTES = 18 * 1024 * 1024;
const assetsRoot = fileURLToPath(new URL("../dist/assets/", import.meta.url));
const files = walkFiles(assetsRoot);
const assetBytes = sum(files.map((path) => statSync(path).size));
const javascriptBytes = sum(
  files.filter((path) => path.endsWith(".js")).map((path) => statSync(path).size),
);

if (files.length > MAX_ASSET_COUNT) {
  throw new Error(`Product bundle has ${files.length} assets; budget is ${MAX_ASSET_COUNT}`);
}
if (assetBytes > MAX_ASSET_BYTES) {
  throw new Error(`Product assets use ${assetBytes} bytes; budget is ${MAX_ASSET_BYTES}`);
}
if (javascriptBytes > MAX_JAVASCRIPT_BYTES) {
  throw new Error(
    `Product JavaScript uses ${javascriptBytes} bytes; budget is ${MAX_JAVASCRIPT_BYTES}`,
  );
}

console.log(
  `Product bundle budget passed: ${files.length} assets, ${assetBytes} bytes total, ${javascriptBytes} JavaScript bytes.`,
);

// Include the entry and every static dependency, counting shared chunks once.
// Dynamic editor and preview chunks belong to their interaction, not first display.
const distRoot = fileURLToPath(new URL("../dist/", import.meta.url));
const manifest = JSON.parse(readFileSync(join(distRoot, ".vite/manifest.json"), "utf8"));
const routeBudgets = [
  { name: null, bytes: 1_100_000, gzip: 340_000 },
  { name: "LandingPage", bytes: 1_160_000, gzip: 360_000 },
  { name: "DataPage", bytes: 1_220_000, gzip: 380_000 },
  { name: "ResearchWorkspacePage", bytes: 1_530_000, gzip: 475_000 },
  { name: "ResearchRunsPage", bytes: 1_730_000, gzip: 540_000 },
  { name: "DailyTracksPage", bytes: 1_680_000, gzip: 525_000 },
  { name: "ChatPage", bytes: 3_040_000, gzip: 930_000 },
];
for (const budget of routeBudgets) {
  const files = new Set();
  function visit(key) {
    const chunk = manifest[key];
    if (!chunk) throw new Error(`Missing manifest chunk: ${key}`);
    if (files.has(chunk.file)) return;
    files.add(chunk.file);
    for (const imported of chunk.imports ?? []) visit(imported);
  }
  visit("index.html");
  if (budget.name !== null) {
    const entries = Object.entries(manifest).filter(([, chunk]) => chunk.isDynamicEntry && chunk.name === budget.name);
    if (entries.length !== 1) throw new Error(`Expected one route entry for ${budget.name}`);
    visit(entries[0][0]);
  }
  const content = [...files].map(file => readFileSync(join(distRoot, file)));
  const bytes = sum(content.map(buffer => buffer.byteLength));
  const gzip = sum(content.map(buffer => gzipSync(buffer).byteLength));
  const label = budget.name ?? "Entry";
  if (bytes > budget.bytes || gzip > budget.gzip) {
    throw new Error(`${label} initial JavaScript uses ${bytes} bytes / ${gzip} gzip; budget is ${budget.bytes} / ${budget.gzip}`);
  }
  console.log(`${label} initial JavaScript budget passed: ${bytes} bytes, ${gzip} gzip.`);
}

function walkFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? walkFiles(path) : [path];
  });
}

function sum(values) {
  return values.reduce((total, value) => total + value, 0);
}
