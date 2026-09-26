import ts from "typescript";

const basicControls = new Set(["button", "input", "select", "textarea", "dialog", "table", "details", "summary"]);
// The Runs file still hosts legacy list controls until ticket 08.
// Enforce the migrated run detail and its shared controls without exempting them.
const migratedRunsFunctions = new Set([
  "ResearchRunDetail", "ResearchDeleteDialog", "ResearchRunProgressView", "UseAsDraftPanel",
  "ResearchOrganizationPanel", "ResearchFolderSelect",
]);

export function isMigratedUiFile(relativePath) {
  return relativePath === "main.tsx" || relativePath === "shell/AppShell.tsx" ||
    relativePath === "chat/SessionHistoryList.tsx" || relativePath.startsWith("auth/") ||
    relativePath.startsWith("research/") ||
    ["research-runs/FactorResultView.tsx", "research-runs/StrategyResultView.tsx", "components/layout/Disclosure.tsx"].includes(relativePath) ||
    relativePath === "components/product/MetricGroup.tsx" ||
    ["FactorEvidence", "CommonInputObservations", "MetricHelp", "StrategyPerformanceChart", "StrategyComparisonPanel", "DailyHoldings", "StrategyEvents", "StrategyEventDetails", "FrameworkDecisionDetails", "CloseRiskFacts", "CurrentDataRerun"].some(
      (name) => relativePath === `analysis/${name}.tsx`,
    );
}

/** Return source-level ownership violations without depending on rendered DOM. */
export function uiOwnershipViolations(relativePath, source, migrated) {
  const isFoundation = relativePath.startsWith("components/ui/");
  const file = ts.createSourceFile(relativePath, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const violations = [];

  function report(node, description) {
    const position = file.getLineAndCharacterOfPosition(node.getStart(file));
    violations.push(`${relativePath}:${position.line + 1}: ${description}`);
  }

  function visit(node, inMigratedFunction = false) {
    const scopedMigration = inMigratedFunction || (
      relativePath === "research-runs/ResearchRunsPage.tsx" && ts.isFunctionDeclaration(node) &&
      migratedRunsFunctions.has(node.name?.text)
    );
    if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)) {
      const moduleName = node.moduleSpecifier.text;
      if (!isFoundation && (moduleName === "@base-ui/react" || moduleName.startsWith("@base-ui/react/") || moduleName === "radix-ui" || moduleName.startsWith("@radix-ui/"))) {
        report(node, `import ${moduleName} through components/ui`);
      }
    }
    if ((migrated || scopedMigration) && !isFoundation && (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node))) {
      const name = node.tagName.getText(file);
      if (basicControls.has(name)) report(node, `replace native <${name}> with components/ui`);
    }
    ts.forEachChild(node, child => visit(child, scopedMigration));
  }

  visit(file);
  return violations;
}
