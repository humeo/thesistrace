import "../../src/styles.css";
import { createRoot } from "react-dom/client";
import { changeInterfaceLanguage, interfaceLocale } from "../../src/i18n";
import { OperatorResearchersPage } from "../../src/operator/OperatorResearchersPage";
import { LanguageControls } from "./language-controls";
// Test-only shortcut permits a locale change while a modal correctly makes the outer controls inert.
window.addEventListener("keydown", event => { if (event.ctrlKey && event.shiftKey && event.key.toLowerCase() === "l") void changeInterfaceLanguage(interfaceLocale() === "en" ? "zh-CN" : "en"); });
createRoot(document.getElementById("root")!).render(<><LanguageControls /><main style={{ padding: 16 }}><OperatorResearchersPage operatorResearcherId="00000000-0000-4000-8000-000000000001" /></main></>);
