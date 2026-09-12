import { useState } from "react";
import { createRoot } from "react-dom/client";
import { AlphaFormulaEditor } from "../../src/research/AlphaFormulaEditor";
import { parser } from "../../src/research/alpha-language-parser";

function Fixture() {
  const [formula, setFormula] = useState("");
  const [selection, setSelection] = useState({ anchor: 0, head: 0 });
  const [errors, setErrors] = useState(0);
  return <>
    <h2 id="alpha-formula-title">Alpha formula</h2>
    <div style={{ height: 240 }}><AlphaFormulaEditor
      catalog={{ fields: [], builtins: [] }} diagnostics={[]}
      formula={formula} selection={selection}
      onChange={(source, nextSelection) => {
        setFormula(source); setSelection(nextSelection);
        let count = 0;
        parser.parse(source).iterate({ enter(node) { if (node.type.isError) count++; } });
        setErrors(count);
      }}
    /></div>
    <output aria-label="Saved formula">{formula}</output>
    <output aria-label="Syntax errors">{errors}</output>
  </>;
}
createRoot(document.getElementById("root")!).render(<Fixture />);
