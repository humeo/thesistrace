import { createRoot } from "react-dom/client";
import { OperatorDatasetStatus } from "../../src/operator/OperatorDatasetStatus";
import { changeInterfaceLanguage } from "../../src/i18n";

createRoot(document.getElementById("root")!).render(
  <main className="operator-page">
    <nav aria-label="Fixture language">
      <button onClick={() => changeInterfaceLanguage("en")}>English</button>
      <button onClick={() => changeInterfaceLanguage("zh-CN")}>简体中文</button>
    </nav>
    <h1>Data operations</h1>
    <OperatorDatasetStatus
      reloadGeneration={0}
      onAccessNotFound={() => { throw new Error("Unexpected access rejection"); }}
    />
  </main>,
);
