import { ArrowClockwise } from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "../i18n";
import { formatNumber, formatTimestamp } from "../i18n/format";
import { checkConnection, loadConnections, revokeApp, type AuthorizedApp, type Connection } from "./api";
import { McpSetup } from "./McpSetup";
import { scopeLabel } from "./setup";
import { McpTools } from "./McpTools";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Alert, AlertDescription } from "../components/ui/alert";
import { Card, CardHeader, CardTitle, CardContent } from "../components/ui/card";
import { Empty, EmptyHeader, EmptyTitle } from "../components/ui/empty";
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter } from "../components/ui/alert-dialog";
import { Page, PageContent, PageHeader } from "../components/layout/Page";
import { Separator } from "../components/ui/separator";
import { Skeleton } from "../components/ui/skeleton";
import { mcpLayout } from "./mcpLayout";

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
  const revokeTrigger = useRef<HTMLButtonElement | null>(null);
  const appsHeading = useRef<HTMLHeadingElement>(null);
  const cancelTrigger = useRef<HTMLButtonElement>(null);
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
  async function revokeSelected() {
    if (!selected || revoking) return;
    setRevoking(true); setRevokeError(false);
    try {
      await revokeApp(selected.id);
      setCatalog(current => current ? { ...current, apps: current.apps.filter(app => app.client_id !== selected.client_id) } : null);
      setNotice({ name: selected.name || selected.client_id }); setSelected(null);
    } catch { setRevokeError(true); }
    finally { setRevoking(false); }
  }
  return <Page className="console-workspace" aria-label="MCP"><PageContent width="wide" className={mcpLayout.page}>
    <PageHeader variant="console" className="mb-0" title="MCP" description={t("subtitle")} badges={<Badge variant={status === "available" ? "success" : status === "unavailable" ? "destructive" : "secondary"} role="status">{t(status)}</Badge>} actions={<div className={mcpLayout.row}><small className="text-xs text-muted-foreground">{checkedAt ? t("checked", { time: formatTimestamp(checkedAt, { hour: "numeric", minute: "2-digit", second: "2-digit" }) }) : t("notChecked")}</small><Button variant="ghost" size="sm" disabled={status === "checking"} onClick={() => void check()}><ArrowClockwise data-icon="inline-start" />{status === "checking" ? t("checking") : t("checkService")}</Button></div>} />
    {status === "unavailable" || catalogError ? <div className={mcpLayout.stack}>
      {status === "unavailable" ? <Alert role="status"><AlertDescription>{t("serviceError")}</AlertDescription></Alert> : null}
      {catalogError ? <Alert variant="destructive"><AlertDescription>{t("catalogError")}</AlertDescription><Button variant="outline" onClick={() => void load()}>{t("retry")}</Button></Alert> : null}
    </div> : null}
    {catalog ? <McpSetup endpoint={catalog.server_url} /> : <Skeleton className="h-64 w-full" />}
    <Separator />
    <section className="grid min-w-0 grid-cols-[200px_minmax(0,1fr)] items-start gap-6" aria-labelledby="mcp-apps-heading">
        <div className={mcpLayout.row}><h2 ref={appsHeading} tabIndex={-1} id="mcp-apps-heading" className={mcpLayout.sectionTitle}>{t("authorizedApps")}</h2>{catalog && !catalogError ? <span className="text-sm text-muted-foreground">{formatNumber(catalog.apps.length)}</span> : null}</div>
        <div className="flex min-w-0 flex-col gap-3">
        {catalog && catalog.apps.length > 0 ? <p className="m-0 text-sm text-muted-foreground">{t("appDescription")}</p> : null}
        {notice ? <p role="status" className="m-0 text-sm text-muted-foreground">{t("revoked", notice)}</p> : null}
        {!catalog || catalogError ? <p className="m-0 text-sm text-muted-foreground">{catalogError ? t("appUnverified") : t("loadingApps")}</p> : catalog.apps.length === 0 ? <Empty className="flex-none items-start justify-start p-0 text-left"><EmptyHeader className="items-start"><EmptyTitle>{t("noApps")}</EmptyTitle></EmptyHeader></Empty> : <div className="grid min-w-0 grid-cols-2 items-start gap-4">{catalog.apps.map(app => <article aria-label={app.name || app.client_id} key={app.id}>
          <Card><CardHeader className="flex-row items-center justify-between"><CardTitle>{app.name || app.client_id}</CardTitle><Badge variant="secondary">{t("authorized")}</Badge></CardHeader><CardContent className={mcpLayout.stack}>
            <div className="border-t border-border pt-3 text-xs font-medium text-muted-foreground">{t("permission")}</div>
            <ul className="grid gap-1">{app.scopes.map(scope => <li key={scope}>{scopeLabel(scope)}</li>)}</ul>
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3"><p>{t("authorizedAt", { time: formatTimestamp(app.authorized_at, { dateStyle: "medium", timeStyle: "short" }) })}</p>
            <Button variant="outline" onClick={event => { revokeTrigger.current = event.currentTarget; setRevokeError(false); setSelected(app); }}>{t("revoke")}<span className="sr-only">{t("revokeFor", { name: app.name || app.client_id })}</span></Button></div>
          </CardContent></Card>
        </article>)}</div>}
        </div>
    </section>
    <Separator />
    <McpTools tools={connection?.tools ?? null} checking={status === "checking"} />
    <AlertDialog open={selected !== null} onOpenChange={open => { if (!open && !revoking) setSelected(null); }}>
      <AlertDialogContent initialFocus={cancelTrigger} finalFocus={() => revokeTrigger.current?.isConnected ? revokeTrigger.current : appsHeading.current}>
        <AlertDialogHeader><AlertDialogTitle>{t("revokeTitle", { name: selected?.name || selected?.client_id || "" })}</AlertDialogTitle><AlertDialogDescription>{t("revokeDescription")}</AlertDialogDescription></AlertDialogHeader>
        {revokeError ? <Alert variant="destructive">{t("revokeError")}</Alert> : null}
        <AlertDialogFooter><Button ref={cancelTrigger} variant="outline" disabled={revoking} onClick={() => setSelected(null)}>{t("cancel")}</Button><Button variant="destructive" disabled={revoking} onClick={() => void revokeSelected()}>{revoking ? t("revoking") : t("revoke")}</Button></AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </PageContent></Page>;
}
