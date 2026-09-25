import ts from "typescript";

const basicControls = new Set(["button", "input", "select", "textarea", "dialog", "table", "details", "summary"]);

export function isMigratedUiFile(relativePath) {
  return relativePath === "main.tsx" ||
    (relativePath.startsWith("auth/") && relativePath !== "auth/AccountMenu.tsx");
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

  function visit(node) {
    if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)) {
      const moduleName = node.moduleSpecifier.text;
      if (!isFoundation && (moduleName === "@base-ui/react" || moduleName.startsWith("@base-ui/react/") || moduleName === "radix-ui" || moduleName.startsWith("@radix-ui/"))) {
        report(node, `import ${moduleName} through components/ui`);
      }
    }
    if (migrated && !isFoundation && (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node))) {
      const name = node.tagName.getText(file);
      if (basicControls.has(name)) report(node, `replace native <${name}> with components/ui`);
    }
    ts.forEachChild(node, visit);
  }

  visit(file);
  return violations;
}
