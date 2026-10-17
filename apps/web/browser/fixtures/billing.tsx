import "../../src/styles.css";
import { createRoot } from "react-dom/client";
import { BillingPage } from "../../src/billing/BillingPage";
import { WorkspaceQueryProvider } from "../../src/shell/WorkspaceQueryProvider";
import { LanguageControls } from "./language-controls";
createRoot(document.getElementById("root")!).render(
  <WorkspaceQueryProvider researcherId="billing-fixture">
    <LanguageControls />
    <BillingPage />
  </WorkspaceQueryProvider>,
);
