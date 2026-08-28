import React, { useCallback, useEffect, useState } from "react";
import ReactDOM from "react-dom/client";

import { AuthProvider, useAuth } from "./auth/AuthProvider";
import { AuthRoute, AuthSurface, returnToFromLocation } from "./auth/AuthPages";
import {
  extractInitialAuthSecret,
  isAuthPath,
  isProductPath,
  locationHref,
  type BrowserLocation,
  type InitialAuthSecret,
} from "./auth/routing";
import { authenticatedResearcherId } from "./auth/session";
import { CoreApp } from "./shell/CoreApp";
import "./styles.css";

function browserLocation(): BrowserLocation {
  return {
    pathname: window.location.pathname === "/" ? "/data" : window.location.pathname,
    search: window.location.search,
    hash: window.location.hash,
  };
}

const extracted = extractInitialAuthSecret(browserLocation());
if (
  window.location.pathname === "/"
  || locationHref(extracted.location) !== `${window.location.pathname}${window.location.search}${window.location.hash}`
) {
  window.history.replaceState(null, "", locationHref(extracted.location));
}

function BrowserRoutedApp() {
  const { state, retry } = useAuth();
  const researcherId = authenticatedResearcherId(state);
  const [location, setLocation] = useState(browserLocation);
  const [secret, setSecret] = useState<InitialAuthSecret | null>(extracted.secret);

  const navigate = useCallback((path: string, options?: Readonly<{ replace?: boolean }>) => {
    if (options?.replace) window.history.replaceState(null, "", path);
    else window.history.pushState(null, "", path);
    setLocation(browserLocation());
  }, []);

  useEffect(() => {
    const handleLocationChange = () => setLocation(browserLocation());
    window.addEventListener("popstate", handleLocationChange);
    return () => window.removeEventListener("popstate", handleLocationChange);
  }, []);

  const anonymousRedirect = state.status === "anonymous" && !isAuthPath(location.pathname)
    ? `/login?returnTo=${encodeURIComponent(isProductPath(location.pathname)
      ? locationHref(location)
      : "/data")}`
    : null;
  const authenticatedRedirect = state.status === "authenticated" && isAuthPath(location.pathname)
    ? returnToFromLocation(location) ?? "/data"
    : state.status === "authenticated" && !isProductPath(location.pathname)
      ? "/data"
      : null;
  useEffect(() => {
    const destination = anonymousRedirect ?? authenticatedRedirect;
    if (destination !== null) navigate(destination, { replace: true });
  }, [anonymousRedirect, authenticatedRedirect, navigate]);

  if (state.status === "loading") {
    return <AuthStatus title="Checking access" message="Verifying your ThesisTrace session…" />;
  }
  if (state.status === "setup") {
    return <AuthStatus title="Preparing workspace" message="Setting up your Research folders…" />;
  }
  if (state.status === "setup-failure") {
    return (
      <AuthStatus
        action={() => void retry()}
        actionLabel="Retry setup"
        message="Your session is valid, but the Research workspace is not ready yet."
        title="Workspace setup unavailable"
      />
    );
  }
  if (state.status === "unavailable") {
    return (
      <AuthStatus
        action={() => void retry()}
        actionLabel="Retry"
        message="Your access state could not be verified. Existing session data has been retained."
        title="Authentication unavailable"
      />
    );
  }
  if (anonymousRedirect !== null || authenticatedRedirect !== null) {
    return <AuthStatus title="Opening ThesisTrace" message="Redirecting…" />;
  }
  if (state.status === "anonymous") {
    return (
      <AuthRoute
        clearSecret={() => setSecret(null)}
        location={location}
        navigate={navigate}
        secret={secret}
      />
    );
  }
  if (researcherId === null) {
    return <AuthStatus title="Opening ThesisTrace" message="Preparing product access…" />;
  }
  return (
    <CoreApp
      currentPath={location.pathname}
      researcherId={researcherId}
    />
  );
}

function AuthStatus({ title, message, action, actionLabel }: {
  title: string;
  message: string;
  action?: () => void;
  actionLabel?: string;
}) {
  return (
    <AuthSurface eyebrow="Research workspace" title={title}>
      <p role="status">{message}</p>
      {action !== undefined ? (
        <button className="button-primary auth-submit" onClick={action} type="button">
          {actionLabel}
        </button>
      ) : null}
    </AuthSurface>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AuthProvider>
      <BrowserRoutedApp />
    </AuthProvider>
  </React.StrictMode>,
);
