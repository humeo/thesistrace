import React from "react";
import ReactDOM from "react-dom/client";

import { CoreApp } from "./CoreApp";

const currentPath = window.location.pathname;
ReactDOM.createRoot(document.getElementById("core-root")!).render(
  <React.StrictMode>
    <CoreApp currentPath={currentPath} />
  </React.StrictMode>,
);
