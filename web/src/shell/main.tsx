import React from "react";
import ReactDOM from "react-dom/client";

import { CoreApp } from "./CoreApp";

ReactDOM.createRoot(document.getElementById("core-root")!).render(
  <React.StrictMode>
    <CoreApp currentPath="/data" />
  </React.StrictMode>,
);
