import { useQuery } from "@tanstack/react-query";
import { Flex, Progress, Tooltip, Typography, theme } from "antd";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { contextWindowSnapshotSchema, type ContextWindowSnapshot } from "@thesistrace/contracts/context-window";


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
  const { data, isPending, isError, refetch } = useQuery({
    queryKey: ["chat-context-window", threadId, modelKey],
    queryFn: ({ signal }) => loadContextWindow(modelKey, threadId, signal),
    staleTime: 5_000,
    refetchInterval: open ? 5_000 : false,
  });
  useEffect(() => { if (open) void refetch(); }, [open, refetch]);
  const snapshot = isError ? undefined : data;
  const used = snapshot?.input_tokens;
  const percent = snapshot && used !== null && used !== undefined ? Math.round(used / snapshot.context_window * 100) : null;
  const summary = percent === null ? t(isPending ? "contextWindow.loading"
    : isError ? "contextWindow.unavailable" : "contextWindow.unmeasured")
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
