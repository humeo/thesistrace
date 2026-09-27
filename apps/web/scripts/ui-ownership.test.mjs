import assert from "node:assert/strict";
import test from "node:test";
import { isProductUiFile, uiOwnershipViolations } from "./ui-ownership.mjs";

test("accepts shared controls and semantic form containers", () => {
  const source = `import { Button } from "@/components/ui/button"; export const Page = () => <form><Button>Run</Button></form>;`;
  assert.deepEqual(uiOwnershipViolations("auth/AuthPages.tsx", source), []);
});

test("rejects a locally restyled basic control anywhere in product code", () => {
  const source = `export const Page = () => <button className="local-button">Run</button>;`;
  for (const path of ["auth/AuthPages.tsx", "operator/FuturePanel.tsx", "analysis/UnusedBefore.tsx"]) {
    assert.equal(isProductUiFile(path), true);
    assert.match(uiOwnershipViolations(path, source)[0], /replace native <button>/);
  }
});

test("rejects native disclosure controls in product code", () => {
  const source = `export const Page = () => <details><summary>More</summary></details>;`;
  assert.equal(uiOwnershipViolations("auth/AccessHelp.tsx", source).length, 2);
  const runs = `function ResearchRunDetail() { return <button>Run</button>; }
    function ResearchRunHistory() { return <button>Legacy list</button>; }`;
  assert.equal(uiOwnershipViolations("research-runs/ResearchRunsPage.tsx", runs).length, 2);
  assert.match(uiOwnershipViolations("research-runs/ResearchRunsPage.tsx", runs)[0], /replace native <button>/);
});

test("rejects direct primitive imports and re-exports outside the foundation", () => {
  for (const source of [
    `import { Button } from "@base-ui/react/button";`,
    `export { Button } from "@base-ui/react/button";`,
    `const primitive = import("@base-ui/react/button");`,
    `const primitive = require("radix-ui");`,
    `const primitive = import("radix-ui/dropdown-menu");`,
  ]) {
    assert.match(uiOwnershipViolations("mcp/McpPage.tsx", source)[0], /through components\/ui/);
    assert.deepEqual(uiOwnershipViolations("components/ui/button.tsx", source), []);
  }
});

test("keeps explicit shadcn and frozen landing native-control exceptions narrow", () => {
  const native = `export const Button = () => <button>Run</button>;`;
  assert.equal(isProductUiFile("components/ui/button.tsx"), false);
  assert.equal(isProductUiFile("landing/LandingPage.tsx"), false);
  assert.equal(isProductUiFile("components/layout/FuturePage.tsx"), true);
  assert.deepEqual(uiOwnershipViolations("components/ui/button.tsx", native), []);
  assert.deepEqual(uiOwnershipViolations("landing/LandingPage.tsx", native), []);
  assert.equal(uiOwnershipViolations("components/layout/FuturePage.tsx", native).length, 1);
});
