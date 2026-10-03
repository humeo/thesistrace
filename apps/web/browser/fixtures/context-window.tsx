import "../../src/styles.css";
import { createRoot } from "react-dom/client";
import { useState } from "react";
import { ChatUiProvider } from "../../src/chat/ChatUiProvider";
import { ContextWindowIndicator } from "../../src/chat/ContextWindowIndicator";
import { LanguageControls } from "./language-controls";

function Fixture() {
  const [modelKey, setModelKey] = useState("luna");
  return <><LanguageControls /><ChatUiProvider><main style={{ padding: 80 }}>
    <ContextWindowIndicator modelKey={modelKey} threadId="00000000-0000-4000-8000-000000000222" />
    <button onClick={() => setModelKey("sol")}>Switch model</button>
  </main></ChatUiProvider></>;
}
createRoot(document.getElementById("root")!).render(<Fixture />);
