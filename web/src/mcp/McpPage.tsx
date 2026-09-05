import { ArrowClockwise, Info, Plug, ShieldCheck } from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { checkConnection, loadConnections, revokeApp, type AuthorizedApp, type Connection } from "./api";
import { CopyButton } from "./CopyButton";
import { McpSetup } from "./McpSetup";
import { scopeLabels } from "./setup";
import { McpTools } from "./McpTools";
import "./mcp.css";

export function McpPage() {
  const [catalog, setCatalog] = useState<Awaited<ReturnType<typeof loadConnections>> | null>(null);
  const [catalogError, setCatalogError] = useState(false);
  const [connection, setConnection] = useState<Connection | null>(null);
  const [status, setStatus] = useState<"checking" | "available" | "unavailable">("checking");
  const [checkedAt, setCheckedAt] = useState<string | null>(null);
  const [selected, setSelected] = useState<AuthorizedApp | null>(null);
  const [revoking, setRevoking] = useState(false);
  const [notice, setNotice] = useState("");
  const [revokeError, setRevokeError] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  const load = useCallback(async (signal?: AbortSignal) => {
    setCatalogError(false);
    try { const data = await loadConnections(signal); if (!signal?.aborted) setCatalog(data); }
    catch { if (!signal?.aborted) setCatalogError(true); }
  }, []);
  const check = useCallback(async (signal?: AbortSignal) => {
    setStatus("checking");
    try {
      const result = await checkConnection(signal);
      if (!signal?.aborted) { setConnection(result); setCheckedAt(result.checked_at); setStatus("available"); }
    } catch { if (!signal?.aborted) { setConnection(null); setCheckedAt(new Date().toISOString()); setStatus("unavailable"); } }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal); void check(controller.signal);
    const refresh = () => { if (document.visibilityState === "visible") void load(controller.signal); };
    window.addEventListener("focus", refresh);
    return () => { controller.abort(); window.removeEventListener("focus", refresh); };
  }, [load, check]);
  useEffect(() => { if (selected) { setRevokeError(""); dialog.current?.showModal(); } }, [selected]);
  function closeDialog() { if (revoking) return; dialog.current?.close(); setSelected(null); }
  return <section className="page-section mcp-page" aria-labelledby="mcp-page-heading">
    <header className="mcp-page-heading"><h1 id="mcp-page-heading">MCP</h1><p>Connect your AI assistant to your research.</p></header>
    <section aria-labelledby="mcp-connection-heading"><h2 id="mcp-connection-heading">Connection</h2>
      <div className="mcp-service"><div className="mcp-service-name"><Plug size={23} /><div><strong>ThesisTrace</strong><span>Research tools for your AI assistants</span></div></div>
        <div role="status" className="mcp-service-status"><span className={`mcp-status mcp-status-${status}`}>{status === "checking" ? "Checking…" : status === "available" ? "Available" : "Unavailable"}</span><small>{checkedAt ? `Checked ${new Date(checkedAt).toLocaleTimeString()}` : "Not checked yet"}</small></div>
        <button type="button" disabled={status === "checking"} onClick={() => void check()}><ArrowClockwise size={15} />{status === "checking" ? "Checking…" : "Check connection"}</button>
      </div>
      {catalog ? <div className="mcp-endpoint"><span>Server URL</span><code>{catalog.server_url}</code><CopyButton text={catalog.server_url} label="Copy URL" /></div> : !catalogError ? <p role="status">Loading server details…</p> : null}
      {status === "unavailable" ? <p className="mcp-feedback" role="status">The connection could not be verified. Check again before reconnecting.</p> : null}
      {catalogError ? <div className="mcp-feedback" role="alert">Server details and app access could not be refreshed. <button type="button" onClick={() => void load()}>Retry</button></div> : null}
    </section>
    {catalog ? <McpSetup endpoint={catalog.server_url} /> : null}
    <div className="mcp-library">
      <McpTools tools={connection?.tools ?? null} checking={status === "checking"} />
      <section className="mcp-apps" aria-labelledby="mcp-apps-heading">
        <div className="mcp-section-heading"><h2 id="mcp-apps-heading">Authorized apps</h2>{catalog && !catalogError ? <span className="mcp-tag">{catalog.apps.length}</span> : null}</div>
        <p className="mcp-muted">AI clients you have given access to ThesisTrace.</p>
        <div role="status">{notice}</div>
        {!catalog || catalogError ? <p>{catalogError ? "App access is not verified. Retry above." : "Loading authorized apps…"}</p> : catalog.apps.length === 0 ? <div className="mcp-empty"><ShieldCheck size={23} /><div><strong>No authorized apps yet</strong><p>After you sign in from an AI client and allow access, it will appear here.</p></div></div> : catalog.apps.map(app => <article className="mcp-app" key={app.id}>
          <div className="mcp-section-heading"><strong>{app.name || app.client_id}</strong><span className="mcp-tag">Authorized</span></div>
          <ul>{app.scopes.map(scope => <li key={scope}>{scopeLabels[scope] ?? scope}</li>)}</ul>
          <p className="mcp-muted">Authorized {new Date(app.authorized_at).toLocaleString()}</p>
          <button type="button" onClick={() => setSelected(app)}>Revoke access<span className="visually-hidden"> for {app.name || app.client_id}</span></button>
        </article>)}
        <p className="mcp-app-note"><Info size={14} />Authorization allows access. It does not mean the app is currently online.</p>
      </section>
    </div>
    <dialog className="mcp-dialog" ref={dialog} aria-labelledby="mcp-revoke-title" onCancel={event => { if (revoking) event.preventDefault(); else setSelected(null); }}>
      {selected ? <><h2 id="mcp-revoke-title">Revoke {selected.name || selected.client_id} access?</h2><p>This app will need your permission again before it can use ThesisTrace tools.</p>
        {revokeError ? <p role="alert">{revokeError}</p> : null}
        <footer><button type="button" onClick={closeDialog} disabled={revoking}>Cancel</button><button className="mcp-danger" type="button" disabled={revoking} onClick={async () => {
          if (revoking) return;
          setRevoking(true); setRevokeError("");
          try { await revokeApp(selected.id); setCatalog(current => current ? { ...current, apps: current.apps.filter(app => app.client_id !== selected.client_id) } : null); setNotice(`${selected.name || selected.client_id} access revoked.`); dialog.current?.close(); setSelected(null); }
          catch { setRevokeError("Access could not be revoked. Please try again."); }
          finally { setRevoking(false); }
        }}>{revoking ? "Revoking…" : "Revoke access"}</button></footer></> : null}
    </dialog>
  </section>;
}
