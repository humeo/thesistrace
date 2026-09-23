import { useEffect, useState } from "react";
import { useAuth } from "../auth/AuthProvider";
import { coreFetch } from "../auth/coreFetch";
import { useTranslation } from "../i18n";
import { scopeLabel } from "./setup";
import "./mcp.css";
export function McpAuthorizePage({ search }: { search: string }) {
  const { t } = useTranslation("mcp");
  const { state } = useAuth();
  const [request, setRequest] = useState<{ name: string; scopes: string[] } | null>(null);
  const [error, setError] = useState<"invalidRequest" | "authorizationFailed" | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setRequest(null); setError(null);
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
    if (busy) return;
    setBusy(true); setError(null);
    try {
      const response = await coreFetch("/api/auth/oauth2/consent", { method: "POST", body: JSON.stringify({ accept, oauth_query: search.slice(1) }) });
      if (!response.ok) throw new Error();
      const data = await response.json() as { url: string; redirect: boolean };
      if (!data.url) throw new Error();
      // Only the OAuth server selects the already-validated client callback.
      window.location.assign(data.url);
    } catch { setError("authorizationFailed"); setBusy(false); }
  }
  return <section className="page-section mcp-page mcp-authorization">
    <h1>{request ? t("allowTitle", { name: request.name }) : t("authorizeAssistant")}</h1>
    <p>{t("signedInAs")} <strong>{state.session?.email}</strong></p>
    {request ? <><h2>{t("canDo")}</h2><ul>{request.scopes.map(scope => <li key={scope}>{scopeLabel(scope)}</li>)}</ul><p>{t("revokeAnytime")}</p></> : !error ? <p role="status">{t("checkingRequest")}</p> : null}
    {error ? <p role="alert">{t(error)}</p> : null}
    {request ? <footer><button type="button" disabled={busy} onClick={() => void consent(false)}>{t("cancel")}</button><button className="mcp-primary" type="button" disabled={busy} onClick={() => void consent(true)}>{busy ? t("continuing") : t("allowAccess")}</button></footer> : null}
  </section>;
}
