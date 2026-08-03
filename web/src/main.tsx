import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import { HostedAuthBoundary } from "./hostedAuth";
import { CoreApp, isCoreRoute } from "./shell/CoreApp";

const pathname = window.location.pathname;
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {isCoreRoute(pathname) ? (
      <CoreApp currentPath={pathname} />
    ) : (
      <HostedAuthBoundary>
        <App />
      </HostedAuthBoundary>
    )}
  </React.StrictMode>,
);
