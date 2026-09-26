import assert from "node:assert/strict";
import test from "node:test";
import { isMigratedUiFile, uiOwnershipViolations } from "./ui-ownership.mjs";

test("accepts shared controls and semantic form containers", () => {
  const source = `import { Button } from "@/components/ui/button"; export const Page = () => <form><Button>Run</Button></form>;`;
  assert.deepEqual(uiOwnershipViolations("auth/AuthPages.tsx", source, true), []);
});

test("rejects a locally restyled basic control in migrated code", () => {
  const source = `export const Page = () => <button className="local-button">Run</button>;`;
  assert.match(uiOwnershipViolations("auth/AuthPages.tsx", source, true)[0], /replace native <button>/);
});

test("rejects native disclosure controls in migrated code", () => {
  const source = `export const Page = () => <details><summary>More</summary></details>;`;
  assert.equal(isMigratedUiFile("auth/AccessHelp.tsx"), true);
  assert.equal(uiOwnershipViolations("auth/AccessHelp.tsx", source, isMigratedUiFile("auth/AccessHelp.tsx")).length, 2);
  assert.equal(isMigratedUiFile("auth/AccountMenu.tsx"), true);
  assert.equal(isMigratedUiFile("shell/AppShell.tsx"), true);
  assert.equal(isMigratedUiFile("chat/SessionHistoryList.tsx"), true);
  assert.equal(isMigratedUiFile("analysis/FactorEvidence.tsx"), true);
  assert.equal(isMigratedUiFile("research-runs/FactorResultView.tsx"), true);
  assert.equal(isMigratedUiFile("research-runs/ResearchRunsPage.tsx"), false);
  const runs = `function ResearchRunDetail() { return <button>Run</button>; }
    function ResearchRunHistory() { return <button>Legacy list</button>; }`;
  assert.equal(uiOwnershipViolations("research-runs/ResearchRunsPage.tsx", runs, false).length, 1);
  assert.match(uiOwnershipViolations("research-runs/ResearchRunsPage.tsx", runs, false)[0], /replace native <button>/);
});

test("rejects primitive imports outside the foundation even before migration", () => {
  const source = `import { Button } from "@base-ui/react/button";`;
  assert.match(uiOwnershipViolations("mcp/McpPage.tsx", source, false)[0], /through components\/ui/);
  assert.deepEqual(uiOwnershipViolations("components/ui/button.tsx", source, true), []);
});
