import React from "react";
import ReactDOM from "react-dom/client";

import { AppShell } from "./AppShell";

ReactDOM.createRoot(document.getElementById("core-root")!).render(
  <React.StrictMode>
    <AppShell currentPath="/data">
      <div aria-label="Resource outlet" />
    </AppShell>
  </React.StrictMode>,
);
