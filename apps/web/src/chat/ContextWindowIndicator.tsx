import { Flex, Progress, Tooltip, Typography, theme } from "antd";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { contextWindowSnapshotSchema, type ContextWindowSnapshot } from "@thesistrace/contracts/context-window";

type SnapshotState = Readonly<{ identity: string; status: "loading" | "unavailable" | "ready"; snapshot?: ContextWindowSnapshot }>;

export async function loadContextWindow(modelKey: string, threadId: string | null, signal: AbortSignal): Promise<ContextWindowSnapshot> {
  const query = new URLSearchParams({ model_key: modelKey });
  if (threadId !== null) query.set("thread_id", threadId);
  const response = await fetch(`/api/agent/context-window?${query}`, {
    credentials: "same-origin", signal: AbortSignal.any([signal, AbortSignal.timeout(5_000)]),
  });
  if (!response.ok) throw new Error("CONTEXT_WINDOW_UNAVAILABLE");
  const snapshot = contextWindowSnapshotSchema.parse(await response.json());
  if (snapshot.model_key !== modelKey) throw new Error("CONTEXT_WINDOW_INVALID");
  return snapshot;
}

export function ContextWindowIndicator({ modelKey, threadId }: { modelKey: string; threadId: string | null }) {
  const { t } = useTranslation("chat");
  const { token } = theme.useToken();
  const [open, setOpen] = useState(false);
  const identity = `${modelKey}:${threadId ?? "new"}`;
  const [state, setState] = useState<SnapshotState>({ identity, status: "loading" });
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function refresh() {
      try {
        const snapshot = await loadContextWindow(modelKey, threadId, controller.signal);
        if (!controller.signal.aborted) setState({ identity, status: "ready", snapshot });
      } catch {
        if (!controller.signal.aborted) setState({ identity, status: "unavailable" });
      }
      if (open && !controller.signal.aborted) timer = setTimeout(() => void refresh(), 5_000);
    }
    void refresh();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [identity, modelKey, open, threadId]);
  const current = state.identity === identity ? state : { identity, status: "loading" as const };
  const snapshot = current.status === "ready" ? current.snapshot : undefined;
  const used = snapshot?.input_tokens;
  const percent = snapshot && used !== null && used !== undefined ? Math.round(used / snapshot.context_window * 100) : null;
  const summary = percent === null ? t(current.status === "loading" ? "contextWindow.loading"
    : current.status === "unavailable" ? "contextWindow.unavailable" : "contextWindow.unmeasured")
    : t("contextWindow.percent", { used: percent, left: Math.max(0, 100 - percent) });
  const compact = (value: number) => new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(value).replace("K", "k");
  return <Tooltip placement="top" trigger={["hover", "focus"]} open={open} onOpenChange={setOpen}
    title={<Flex vertical align="center" gap={4} style={{ textAlign: "center" }}>
      <span>{t("contextWindow.title")}</span>
      <span>{summary}</span>
      {snapshot ? <span>{t("contextWindow.tokens", { used: used === null || used === undefined ? "—" : compact(used), limit: compact(snapshot.context_window) })}</span> : null}
      {percent !== null ? <><span style={{ fontSize: 12, opacity: .7 }}>{t("contextWindow.estimate")}</span>
        <span style={{ fontSize: 12, opacity: .7 }}>{new Date(snapshot!.measured_at!).toLocaleString()}</span></> : null}
    </Flex>}>
    <Typography.Text type="secondary" tabIndex={0} aria-label={`${t("contextWindow.title")}：${summary}`}
      onKeyDown={event => { if (event.key === "Escape") setOpen(false); }}
      style={{ display: "inline-flex", alignItems: "center", height: 32, paddingInline: 4 }}>
      <Progress type="circle" size={14} strokeWidth={16} showInfo={false} status="normal"
        percent={Math.min(100, percent ?? 0)} strokeColor={token.colorTextSecondary}
        railColor={token.colorTextTertiary} aria-hidden="true" />
    </Typography.Text>
  </Tooltip>;
}
