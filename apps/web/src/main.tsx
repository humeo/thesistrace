import React, { Suspense, lazy, useCallback, useEffect, useState } from "react";
import ReactDOM from "react-dom/client";

import { useAuthRetry } from "./auth/useAuthRetry";
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
import { CoreApp } from "./shell/CoreApp";
import { synchronizeEntryLanguage, useTranslation } from "./i18n";
import { Button } from "./components/ui/button";
import { Alert, AlertDescription } from "./components/ui/alert";
import { Spinner } from "./components/ui/spinner";
import { Toaster } from "./components/ui/toast";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "./components/ui/dialog";
import "./styles.css";

const LandingPage = lazy(() => import('./landing/LandingPage'));

function browserLocation(): BrowserLocation {
  return {
    pathname: window.location.pathname,
    search: window.location.search,
    hash: window.location.hash,
  };
}

type ConsumedBrowserLocation = ReturnType<typeof extractInitialAuthSecret> & Readonly<{
  hadFragment: boolean;
}>;

function consumeBrowserLocation(): ConsumedBrowserLocation {
  const observed = browserLocation();
  const extracted = extractInitialAuthSecret(observed);
  if (
    locationHref(extracted.location) !== `${window.location.pathname}${window.location.search}${window.location.hash}`
  ) {
    window.history.replaceState(null, "", locationHref(extracted.location));
  }
  return { ...extracted, hadFragment: observed.hash !== "" };
}

const initialLocation = consumeBrowserLocation();

function BrowserRoutedApp() {
  const { t } = useTranslation("auth");
  const { state, retry } = useAuth();
  const workspaceSession = state.status === "authenticated"
    || (state.status === "unavailable" && state.workspaceReady) ? state.session : null;
  const researcherId = workspaceSession?.researcherId ?? null;
  const [location, setLocation] = useState(browserLocation);
  const [secret, setSecret] = useState<InitialAuthSecret | null>(initialLocation.secret);

  const synchronizeLocation = useCallback(() => {
    const next = consumeBrowserLocation();
    if (isAuthPath(next.location.pathname)) synchronizeEntryLanguage();
    React.startTransition(() => setLocation(next.location));
    setSecret((current) => {
      if (next.secret !== null) return next.secret;
      if (next.hadFragment || current === null) return null;
      const currentPath = "/accept-invitation";
      return next.location.pathname === currentPath ? current : null;
    });
  }, []);

  const navigate = useCallback((path: string, options?: Readonly<{ replace?: boolean }>) => {
    if (options?.replace) window.history.replaceState(null, "", path);
    else window.history.pushState(null, "", path);
    synchronizeLocation();
  }, [synchronizeLocation]);

  useEffect(() => {
    window.addEventListener("hashchange", synchronizeLocation);
    window.addEventListener("popstate", synchronizeLocation);
    return () => {
      window.removeEventListener("hashchange", synchronizeLocation);
      window.removeEventListener("popstate", synchronizeLocation);
    };
  }, [synchronizeLocation]);

  const anonymousRedirect = state.status === "anonymous" && !isAuthPath(location.pathname)
    ? `/login?returnTo=${encodeURIComponent(isProductPath(location.pathname)
      ? locationHref(location)
      : "/data")}`
    : null;
  const oauthQuery = location.pathname === "/login" && new URLSearchParams(location.search).has("sig")
    ? location.search : null;
  useEffect(() => {
    if (state.status === "authenticated" && oauthQuery) {
      window.location.replace(`/api/auth/oauth2/authorize${oauthQuery}`);
    }
  }, [state.status, oauthQuery]);
  const authenticatedRedirect = state.status === "authenticated" && isAuthPath(location.pathname)
    ? oauthQuery ? null : returnToFromLocation(location) ?? "/data"
    : state.status === "authenticated" && !isProductPath(location.pathname)
      ? "/data"
      : null;
  useEffect(() => {
    const destination = anonymousRedirect ?? authenticatedRedirect;
    if (destination !== null) navigate(destination, { replace: true });
  }, [anonymousRedirect, authenticatedRedirect, navigate]);

  if (state.status === "loading") {
    return <AuthStatus title={t("checkingAccess")} message={t("verifyingSession")} />;
  }
  if (state.status === "setup") {
    return <AuthStatus title={t("preparingWorkspace")} message={t("preparingFolders")} />;
  }
  if (state.status === "setup-failure") {
    return (
      <AuthStatus
        action={() => void retry()}
        actionLabel={t("retrySetup")}
        message={t("setupMessage")}
        title={t("setupUnavailable")}
      />
    );
  }
  if (state.status === "unavailable" && workspaceSession === null) {
    return (
      <AuthStatus
        action={() => void retry()}
        actionLabel={t("retry")}
        retryAt={state.retryAt}
        message={t("unavailableMessage")}
        title={t("unavailable")}
      />
    );
  }
  if (anonymousRedirect !== null || authenticatedRedirect !== null) {
    return <AuthStatus title={t("opening")} message={t("redirecting")} />;
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
  if (researcherId === null || workspaceSession === null) {
    return <AuthStatus title={t("opening")} message={t("preparingAccess")} />;
  }
  return (
    <>
      <CoreApp
        key={researcherId}
        location={location}
        navigate={navigate}
        isOperator={workspaceSession.operator}
        researcherId={researcherId}
      />
      <WorkspaceAccessNotice
        unavailable={state.status === "unavailable"}
        retry={retry}
        retryAt={state.status === "unavailable" ? state.retryAt : undefined}
      />
    </>
  );
}

function WorkspaceAccessNotice({ unavailable, retry, retryAt = 0 }: {
  unavailable: boolean;
  retry: () => Promise<void>;
  retryAt?: number;
}) {
  const { t } = useTranslation("auth");
  const cooldown = useAuthRetry(retryAt);
  return <Dialog open={unavailable} disablePointerDismissal onOpenChange={(open, event) => { if (!open) event.cancel(); }}>
    <DialogContent showCloseButton={false}>
      <DialogHeader><DialogTitle>{t("unavailable")}</DialogTitle>
        <DialogDescription>{cooldown > 0 ? t("rateLimited", { seconds: cooldown }) : t("unavailableMessage")}</DialogDescription>
      </DialogHeader>
      <Button disabled={cooldown > 0} onClick={() => void retry()}>{t("retry")}</Button>
    </DialogContent>
  </Dialog>;
}

function AuthStatus({ title, message, action, actionLabel, retryAt = 0 }: {
  title: string;
  message: string;
  action?: () => void;
  actionLabel?: string;
  retryAt?: number;
}) {
  const { t } = useTranslation("auth");
  const cooldown = useAuthRetry(retryAt);
  return (
    <AuthSurface eyebrow={t("workspace")} title={title}>
      {action !== undefined ? (
        <Alert variant="destructive"><AlertDescription>{cooldown > 0 ? t("rateLimited", {seconds: cooldown}) : message}</AlertDescription></Alert>
      ) : (
        <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
          <Spinner aria-hidden="true" />{message}
        </p>
      )}
      {action !== undefined ? (
        <Button className="mt-4 w-full" disabled={cooldown > 0} onClick={action} type="button">
          {actionLabel}
        </Button>
      ) : null}
    </AuthSurface>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {window.location.pathname === "/" ? (
      <Suspense fallback={null}><LandingPage /></Suspense>
    ) : (
      <AuthProvider><BrowserRoutedApp /><Toaster /></AuthProvider>
    )}
  </React.StrictMode>,
);
