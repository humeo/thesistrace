import { ArrowClockwise, Info, ShieldCheck } from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "../i18n";
import { formatNumber, formatTimestamp } from "../i18n/format";
import { checkConnection, loadConnections, revokeApp, type AuthorizedApp, type Connection } from "./api";
import { McpSetup } from "./McpSetup";
import { scopeLabel } from "./setup";
import { McpTools } from "./McpTools";
import { BrandMark } from "../brand/Brand";
import "./mcp.css";

export function McpPage() {
  const { t } = useTranslation("mcp");
  const [catalog, setCatalog] = useState<Awaited<ReturnType<typeof loadConnections>> | null>(null);
  const [catalogError, setCatalogError] = useState(false);
  const [connection, setConnection] = useState<Connection | null>(null);
  const [status, setStatus] = useState<"checking" | "available" | "unavailable">("checking");
  const [checkedAt, setCheckedAt] = useState<string | null>(null);
  const [selected, setSelected] = useState<AuthorizedApp | null>(null);
  const [revoking, setRevoking] = useState(false);
  const [notice, setNotice] = useState<{ name: string } | null>(null);
  const [revokeError, setRevokeError] = useState(false);
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
  useEffect(() => { if (selected) { setRevokeError(false); dialog.current?.showModal(); } }, [selected]);
  function closeDialog() { if (revoking) return; dialog.current?.close(); setSelected(null); }
  return <section className="page-section mcp-page" aria-labelledby="mcp-page-heading">
    <header className="mcp-page-heading"><h1 id="mcp-page-heading">MCP</h1><p>{t("subtitle")}</p></header>
    <section className="mcp-server" aria-labelledby="mcp-connection-heading">
      <div className="mcp-service"><div className="mcp-service-name"><BrandMark size={36} inverse /><div><h2 id="mcp-connection-heading">Quantgrove MCP</h2></div></div>
        <div role="status" className="mcp-service-status"><span className={`mcp-status mcp-status-${status}`}>{t(status)}</span><small>{checkedAt ? t("checked", { time: formatTimestamp(checkedAt, { hour: "numeric", minute: "2-digit", second: "2-digit" }) }) : t("notChecked")}</small></div>
        <button type="button" disabled={status === "checking"} onClick={() => void check()}><ArrowClockwise size={15} />{status === "checking" ? t("checking") : t("checkService")}</button>
      </div>
      {status === "unavailable" ? <p className="mcp-feedback" role="status">{t("serviceError")}</p> : null}
      {catalogError ? <div className="mcp-feedback" role="alert">{t("catalogError")} <button type="button" onClick={() => void load()}>{t("retry")}</button></div> : null}
    </section>
    {catalog ? <McpSetup endpoint={catalog.server_url} /> : null}
    <div className="mcp-library">
      <McpTools tools={connection?.tools ?? null} checking={status === "checking"} />
      <section className="mcp-apps" aria-labelledby="mcp-apps-heading">
        <div className="mcp-section-heading"><h2 id="mcp-apps-heading">{t("authorizedApps")}</h2>{catalog && !catalogError ? <span className="mcp-tag">{formatNumber(catalog.apps.length)}</span> : null}</div>
        <p className="mcp-muted">{t("appDescription")}</p>
        <div role="status">{notice ? t("revoked", notice) : null}</div>
        {!catalog || catalogError ? <p>{catalogError ? t("appUnverified") : t("loadingApps")}</p> : catalog.apps.length === 0 ? <div className="mcp-empty"><ShieldCheck size={23} /><div><strong>{t("noApps")}</strong><p>{t("noAppsDescription")}</p></div></div> : catalog.apps.map(app => <article className="mcp-app" key={app.id}>
          <div className="mcp-section-heading"><strong>{app.name || app.client_id}</strong><span className="mcp-tag">{t("authorized")}</span></div>
          <ul>{app.scopes.map(scope => <li key={scope}>{scopeLabel(scope)}</li>)}</ul>
          <p className="mcp-muted">{t("authorizedAt", { time: formatTimestamp(app.authorized_at, { dateStyle: "medium", timeStyle: "short" }) })}</p>
          <button type="button" onClick={() => setSelected(app)}>{t("revoke")}<span className="visually-hidden">{t("revokeFor", { name: app.name || app.client_id })}</span></button>
        </article>)}
        <p className="mcp-app-note"><Info size={14} />{t("appNote")}</p>
      </section>
    </div>
    <dialog className="mcp-dialog" ref={dialog} aria-labelledby="mcp-revoke-title" onCancel={event => { if (revoking) event.preventDefault(); else setSelected(null); }}>
      {selected ? <><h2 id="mcp-revoke-title">{t("revokeTitle", { name: selected.name || selected.client_id })}</h2><p>{t("revokeDescription")}</p>
        {revokeError ? <p role="alert">{t("revokeError")}</p> : null}
        <footer><button type="button" onClick={closeDialog} disabled={revoking}>{t("cancel")}</button><button className="mcp-danger" type="button" disabled={revoking} onClick={async () => {
          if (revoking) return;
          setRevoking(true); setRevokeError(false);
          try { await revokeApp(selected.id); setCatalog(current => current ? { ...current, apps: current.apps.filter(app => app.client_id !== selected.client_id) } : null); setNotice({ name: selected.name || selected.client_id }); dialog.current?.close(); setSelected(null); }
          catch { setRevokeError(true); }
          finally { setRevoking(false); }
        }}>{revoking ? t("revoking") : t("revoke")}</button></footer></> : null}
    </dialog>
  </section>;
}
