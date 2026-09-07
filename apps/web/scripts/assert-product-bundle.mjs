import { readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const MAX_ASSET_COUNT = 48;
const MAX_ASSET_BYTES = 4 * 1024 * 1024;
const MAX_JAVASCRIPT_BYTES = 3 * 1024 * 1024;
const FORBIDDEN_ASSET_NAME = /(?:mermaid|katex|shiki|code-block)/i;
const assetsRoot = fileURLToPath(new URL("../dist/assets/", import.meta.url));
const files = walkFiles(assetsRoot);
const assetBytes = sum(files.map((path) => statSync(path).size));
const javascriptBytes = sum(
  files.filter((path) => path.endsWith(".js")).map((path) => statSync(path).size),
);
const forbidden = files
  .map((path) => relative(assetsRoot, path))
  .filter((path) => FORBIDDEN_ASSET_NAME.test(path));

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
if (forbidden.length > 0) {
  throw new Error(`Product bundle contains disabled renderer assets: ${forbidden.join(", ")}`);
}

console.log(
  `Product bundle budget passed: ${files.length} assets, ${assetBytes} bytes total, ${javascriptBytes} JavaScript bytes.`,
);

function walkFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? walkFiles(path) : [path];
  });
}

function sum(values) {
  return values.reduce((total, value) => total + value, 0);
}
