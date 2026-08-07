import React from "react";
import ReactDOM from "react-dom/client";

import { CoreApp } from "./shell/CoreApp";
import "./styles.css";

const pathname = window.location.pathname === "/" ? "/data" : window.location.pathname;
if (window.location.pathname === "/") {
  window.history.replaceState(null, "", pathname);
}
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <CoreApp currentPath={pathname} />
  </React.StrictMode>,
);
