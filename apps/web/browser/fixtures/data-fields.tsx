import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import type { AlphaCatalog } from "../../src/alphaCatalog";
import { DataPage } from "../../src/data/DataPage";
import { AlphaFormulaEditor } from "../../src/research/AlphaFormulaEditor";
import type { FormulaDiagnostic } from "../../src/research/diagnostics";
import catalog from "./data-field-catalog.json";
import { changeInterfaceLanguage } from "../../src/i18n";

function DataFieldsFixture() {
  const [formula, setFormula] = useState("");
  const [selection, setSelection] = useState({ anchor: 0, head: 0 });
  const [diagnostics, setDiagnostics] = useState<FormulaDiagnostic[]>([]);
  return <>
    <nav aria-label="Fixture language">
      <button type="button" onClick={() => changeInterfaceLanguage("en")}>English</button>
      <button type="button" onClick={() => changeInterfaceLanguage("zh-CN")}>简体中文</button>
    </nav>
    <DataPage />
    <section style={{ height: 200 }} aria-labelledby="alpha-formula-title">
      <h2 id="alpha-formula-title">Alpha formula</h2>
      <button type="button" onClick={() => {
        setFormula("ts_mean(close, 0)");
        setDiagnostics([{
          code: "WINDOW_OUT_OF_RANGE", severity: "error", message: "Window must be between 1 and 252",
          details: { kind: "window", expected: [1, 252], actual: "0" },
          range: { start: { offset: 15, line: 1, column: 16 }, end: { offset: 16, line: 1, column: 17 } },
        }]);
      }}>Show diagnostic</button>
      <button type="button" onClick={() => {
        setFormula("𠮷 + close");
        setDiagnostics([{
          code: "UNKNOWN_IDENTIFIER", severity: "error", message: "Unknown Alpha identifier: 𠮷",
          details: { kind: "identifier", expected: ["close"], actual: "𠮷" },
          range: { start: { offset: 0, line: 1, column: 1 }, end: { offset: 1, line: 1, column: 2 } },
        }]);
      }}>Show Unicode diagnostic</button>
      <AlphaFormulaEditor catalog={catalog as AlphaCatalog} diagnostics={diagnostics}
        formula={formula} selection={selection} onChange={(value, nextSelection) => {
          setFormula(value);
          setSelection(nextSelection);
        }} />
      <output aria-label="Editor selection">{selection.anchor}:{selection.head}</output>
    </section>
  </>;
}

createRoot(document.getElementById("root")!).render(<DataFieldsFixture />);
