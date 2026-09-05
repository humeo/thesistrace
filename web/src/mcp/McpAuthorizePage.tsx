import { useEffect, useState } from "react";
import { useAuth } from "../auth/AuthProvider";
import { coreFetch } from "../auth/coreFetch";
import { scopeLabels } from "./setup";
import "./mcp.css";
export function McpAuthorizePage({ search }: { search: string }) {
  const { state } = useAuth();
  const [request, setRequest] = useState<{ name: string; scopes: string[] } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setRequest(null); setError("");
    void (async () => {
      try {
        const response = await coreFetch("/api/auth/mcp/authorization", { method: "POST", body: JSON.stringify({ oauth_query: search.slice(1) }), signal: controller.signal });
        if (!response.ok) throw new Error();
        const data = await response.json();
        if (!controller.signal.aborted) setRequest(data);
      } catch { if (!controller.signal.aborted) setError("This authorization request is invalid or has expired. Start again from your AI client."); }
    })();
    return () => controller.abort();
  }, [search]);
  async function consent(accept: boolean) {
    if (busy) return;
    setBusy(true); setError("");
    try {
      const response = await coreFetch("/api/auth/oauth2/consent", { method: "POST", body: JSON.stringify({ accept, oauth_query: search.slice(1) }) });
      if (!response.ok) throw new Error();
      const data = await response.json() as { url: string; redirect: boolean };
      if (!data.url) throw new Error();
      // Only the OAuth server selects the already-validated client callback.
      window.location.assign(data.url);
    } catch { setError("Authorization could not be completed. Start again from your AI client."); setBusy(false); }
  }
  return <section className="page-section mcp-page mcp-authorization">
    <h1>{request ? `Allow ${request.name} to access ThesisTrace?` : "Authorize your AI assistant"}</h1>
    <p>Signed in as <strong>{state.session?.email}</strong></p>
    {request ? <><h2>This app will be able to</h2><ul>{request.scopes.map(scope => <li key={scope}>{scopeLabels[scope] ?? scope}</li>)}</ul><p>You can revoke access from the MCP page at any time.</p></> : !error ? <p role="status">Checking authorization request…</p> : null}
    {error ? <p role="alert">{error}</p> : null}
    {request ? <footer><button type="button" disabled={busy} onClick={() => void consent(false)}>Cancel</button><button className="mcp-primary" type="button" disabled={busy} onClick={() => void consent(true)}>{busy ? "Continuing…" : "Allow access"}</button></footer> : null}
  </section>;
}
