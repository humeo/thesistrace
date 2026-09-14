import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import type { AlphaCatalog } from "../../src/alphaCatalog";
import { DataPage } from "../../src/data/DataPage";
import { AlphaFormulaEditor } from "../../src/research/AlphaFormulaEditor";
import catalog from "./data-field-catalog.json";

function DataFieldsFixture() {
  const [formula, setFormula] = useState("");
  const [selection, setSelection] = useState({ anchor: 0, head: 0 });
  return <>
    <DataPage />
    <section style={{ height: 200 }} aria-labelledby="alpha-formula-title">
      <h2 id="alpha-formula-title">Alpha formula</h2>
      <AlphaFormulaEditor catalog={catalog as AlphaCatalog} diagnostics={[]}
        formula={formula} selection={selection} onChange={(value, nextSelection) => {
          setFormula(value);
          setSelection(nextSelection);
        }} />
    </section>
  </>;
}

createRoot(document.getElementById("root")!).render(<DataFieldsFixture />);
