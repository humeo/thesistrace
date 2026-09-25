import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { isMigratedUiFile, uiOwnershipViolations } from "./ui-ownership.mjs";

const sourceRoot = fileURLToPath(new URL("../src/", import.meta.url));

// Tickets 01–03 own authentication, navigation, and the new research date/field controls. Tickets
// 04–17 will expand this set as each module migrates: research, research-runs, analysis,
// data, daily-tracks, chat, mcp and operator. The public landing retains its
// established markup; specialized editor/chart internals keep their APIs.
function* sourceFiles(directory, prefix = "") {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const relative = `${prefix}${entry.name}`;
    if (entry.isDirectory()) yield* sourceFiles(`${directory}/${entry.name}`, `${relative}/`);
    else if (relative.endsWith(".tsx") && !relative.endsWith(".test.tsx")) yield relative;
  }
}

const violations = [...sourceFiles(sourceRoot)].flatMap(relative =>
  uiOwnershipViolations(relative, readFileSync(`${sourceRoot}/${relative}`, "utf8"), isMigratedUiFile(relative)),
);
if (violations.length > 0) {
  console.error(violations.join("\n"));
  process.exitCode = 1;
} else {
  console.log("UI ownership passed for migrated authentication, navigation and research controls; pending modules are listed in the checker.");
}
