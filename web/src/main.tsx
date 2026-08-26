import React, { useEffect, useState } from "react";
import ReactDOM from "react-dom/client";

import { CoreApp } from "./shell/CoreApp";
import "./styles.css";

function currentPath(): string {
  return window.location.pathname === "/" ? "/data" : window.location.pathname;
}

const pathname = currentPath();
if (window.location.pathname === "/") {
  window.history.replaceState(null, "", pathname);
}

function BrowserRoutedCoreApp() {
  const [pathname, setPathname] = useState(currentPath);

  useEffect(() => {
    const handleLocationChange = () => setPathname(currentPath());
    window.addEventListener("popstate", handleLocationChange);
    return () => window.removeEventListener("popstate", handleLocationChange);
  }, []);

  return <CoreApp currentPath={pathname} />;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRoutedCoreApp />
  </React.StrictMode>,
);
