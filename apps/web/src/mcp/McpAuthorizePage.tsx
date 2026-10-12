import { useEffect, useRef, useState } from "react";
import { useAuth } from "../auth/AuthProvider";
import { coreFetch } from "../auth/coreFetch";
import { useTranslation } from "../i18n";
import { scopeLabel } from "./setup";
import { AuthSurface } from "../auth/AuthPages";
import { Button } from "../components/ui/button";
import { Alert } from "../components/ui/alert";
import { mcpLayout } from "./mcpLayout";
export function McpAuthorizePage({ search }: { search: string }) {
  const { t } = useTranslation("mcp");
  const { state } = useAuth();
  const [request, setRequest] = useState<{ name: string; scopes: string[] } | null>(null);
  const [error, setError] = useState<"invalidRequest" | "authorizationFailed" | "callbackFailed" | null>(null);
  const [busy, setBusy] = useState(false);
  const [decision, setDecision] = useState<boolean | null>(null);
  const authorization = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    authorization.current = controller;
    setRequest(null); setError(null); setDecision(null); setBusy(false);
    void (async () => {
      try {
        const response = await coreFetch("/api/auth/mcp/authorization", { method: "POST", body: JSON.stringify({ oauth_query: search.slice(1) }), signal: controller.signal });
        if (!response.ok) throw new Error();
        const data = await response.json();
        if (!controller.signal.aborted) setRequest(data);
      } catch { if (!controller.signal.aborted) setError("invalidRequest"); }
    })();
    return () => controller.abort();
  }, [search]);
  async function consent(accept: boolean) {
    if (busy || decision !== null) return;
    const signal = authorization.current?.signal;
    if (!signal || signal.aborted) return;
    setBusy(true); setError(null);
    let callback: string;
    try {
      const response = await coreFetch("/api/auth/oauth2/consent", { method: "POST", body: JSON.stringify({ accept, oauth_query: search.slice(1) }), signal });
      if (!response.ok) throw new Error();
      const data = await response.json() as { url: string; redirect: boolean };
      if (!data.url || data.redirect !== true) throw new Error();
      callback = data.url;
    } catch { if (!signal.aborted) { setError("authorizationFailed"); setBusy(false); } return; }
    if (signal.aborted) return;
    setDecision(accept); setBusy(false);
    // Consent is complete even when the client handles the callback without
    // unloading this document. Only Auth selects the validated callback URL.
    try { window.location.assign(callback); }
    catch { setError("callbackFailed"); }
  }
  const title = decision !== null ? t(decision ? "accessApproved" : "accessDenied")
    : request ? t("allowTitle", { name: request.name }) : t("authorizeAssistant");
  return <AuthSurface as="section" eyebrow="MCP" title={title}><div className={mcpLayout.stack}>
    <p>{t("signedInAs")} <strong>{state.session?.email}</strong></p>
    {decision !== null && request ? <p role="status">{t("returnToClient", { name: request.name })}</p>
      : request ? <><h2>{t("canDo")}</h2><ul>{request.scopes.map(scope => <li key={scope}>{scopeLabel(scope)}</li>)}</ul><p>{t("revokeAnytime")}</p></> : !error ? <p role="status">{t("checkingRequest")}</p> : null}
    {error ? <Alert variant="destructive">{t(error)}</Alert> : null}
    {request && decision === null ? <footer className={mcpLayout.row}><Button variant="outline" disabled={busy} onClick={() => void consent(false)}>{t("cancel")}</Button><Button disabled={busy} onClick={() => void consent(true)}>{busy ? t("continuing") : t("allowAccess")}</Button></footer> : null}
  </div></AuthSurface>;
}
