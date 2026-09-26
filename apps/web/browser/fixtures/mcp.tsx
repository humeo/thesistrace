import "../../src/styles.css";
import { createRoot } from "react-dom/client";
import { McpPage } from "../../src/mcp/McpPage";
import { Toaster } from "../../src/components/ui/toast";
import { LanguageControls } from "./language-controls";
createRoot(document.getElementById("root")!).render(<><LanguageControls /><main style={{ padding: 16 }}><McpPage /></main><Toaster /></>);
