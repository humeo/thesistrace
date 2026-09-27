import ts from "typescript";

const basicControls = new Set(["button", "input", "select", "textarea", "dialog", "table", "details", "summary"]);
export function isProductUiFile(relativePath) {
  return relativePath.endsWith(".tsx") && !relativePath.startsWith("components/ui/") && !relativePath.startsWith("landing/");
}

/** Return source-level ownership violations without depending on rendered DOM. */
export function uiOwnershipViolations(relativePath, source) {
  const isFoundation = relativePath.startsWith("components/ui/");
  const isProduct = isProductUiFile(relativePath);
  const file = ts.createSourceFile(relativePath, source, ts.ScriptTarget.Latest, true, relativePath.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const violations = [];

  function report(node, description) {
    const position = file.getLineAndCharacterOfPosition(node.getStart(file));
    violations.push(`${relativePath}:${position.line + 1}: ${description}`);
  }

  function visit(node) {
    const moduleSpecifier = (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)
      ? node.moduleSpecifier
      : ts.isCallExpression(node) && node.arguments.length === 1 && ts.isStringLiteral(node.arguments[0]) &&
          (node.expression.kind === ts.SyntaxKind.ImportKeyword || ts.isIdentifier(node.expression) && node.expression.text === "require")
        ? node.arguments[0]
        : null;
    if (!isFoundation && moduleSpecifier !== null &&
      (moduleSpecifier.text === "@base-ui/react" || moduleSpecifier.text.startsWith("@base-ui/react/") ||
       moduleSpecifier.text === "radix-ui" || moduleSpecifier.text.startsWith("radix-ui/") || moduleSpecifier.text.startsWith("@radix-ui/"))) {
      report(node, `import ${moduleSpecifier.text} through components/ui`);
    }
    if (isProduct && (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node))) {
      const name = node.tagName.getText(file);
      if (basicControls.has(name)) report(node, `replace native <${name}> with components/ui`);
    }
    ts.forEachChild(node, visit);
  }

  visit(file);
  return violations;
}
