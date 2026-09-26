import { Copy, Check } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "../i18n";
import { Button } from "../components/ui/button";
import { toast } from "../components/ui/toast";
export function CopyButton({ text, label, primary = false }: { text: string; label: string; primary?: boolean }) {
  const { t } = useTranslation("mcp");
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  return <span className="inline-flex min-w-0 flex-col gap-1">
    <Button variant={primary ? "default" : "outline"} onClick={async () => {
      clearTimeout(timer.current);
      try { await navigator.clipboard.writeText(text); setState("copied"); toast.add({ title: <CopyFeedback message="copied" />, type: "success" }); }
      catch { setState("failed"); toast.add({ title: <CopyFeedback message="copyFailed" />, type: "error" }); }
      timer.current = setTimeout(() => setState("idle"), 2500);
    }}>{state === "copied" ? <Check data-icon="inline-start" /> : <Copy data-icon="inline-start" />}{state === "copied" ? t("copied") : label}</Button>
    <span role="status">{state === "failed" ? t("copyFailed") : ""}</span>
  </span>;
}

function CopyFeedback({ message }: { message: "copied" | "copyFailed" }) { const { t } = useTranslation("mcp"); return t(message); }
