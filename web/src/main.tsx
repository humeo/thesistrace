import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import { HostedAuthBoundary } from "./hostedAuth";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <HostedAuthBoundary>
      <App />
    </HostedAuthBoundary>
  </React.StrictMode>,
);
