import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { uiOwnershipViolations } from "./ui-ownership.mjs";

const sourceRoot = fileURLToPath(new URL("../src/", import.meta.url));

function* sourceFiles(directory, prefix = "") {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const relative = `${prefix}${entry.name}`;
    if (entry.isDirectory()) yield* sourceFiles(`${directory}/${entry.name}`, `${relative}/`);
    else if (/\.tsx?$/.test(relative) && !/\.(test|spec|d)\.tsx?$/.test(relative)) yield relative;
  }
}

const violations = [...sourceFiles(sourceRoot)].flatMap(relative =>
  uiOwnershipViolations(relative, readFileSync(`${sourceRoot}/${relative}`, "utf8")),
);
if (violations.length > 0) {
  console.error(violations.join("\n"));
  process.exitCode = 1;
} else {
  console.log("UI ownership passed for console and authentication source; only shadcn internals and the public landing are exempt from native-control checks.");
}
