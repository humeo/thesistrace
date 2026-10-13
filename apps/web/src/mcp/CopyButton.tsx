import { Copy, Check } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "../i18n";
import { Button } from "../components/ui/button";
import { toast } from "../components/ui/toast";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "../components/ui/tooltip";
export function CopyButton({ text, label, iconOnly = false }: { text: string; label: string; iconOnly?: boolean }) {
  const { t } = useTranslation("mcp");
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  const button = <Button variant="ghost" size={iconOnly ? "icon-sm" : "sm"} aria-label={state === "copied" ? t("copied") : label} onClick={async () => {
      clearTimeout(timer.current);
      try { await navigator.clipboard.writeText(text); setState("copied"); toast.add({ title: <CopyFeedback message="copied" />, type: "success" }); }
      catch { setState("failed"); toast.add({ title: <CopyFeedback message="copyFailed" />, type: "error" }); }
      timer.current = setTimeout(() => setState("idle"), 2500);
    }}>{state === "copied" ? <Check data-icon="inline-start" /> : <Copy data-icon="inline-start" />}{iconOnly ? null : state === "copied" ? t("copied") : label}</Button>;
  return <span className="inline-flex min-w-0">
    {iconOnly ? <TooltipProvider><Tooltip><TooltipTrigger render={button} /><TooltipContent>{state === "copied" ? t("copied") : label}</TooltipContent></Tooltip></TooltipProvider> : button}
    <span role="status" className="sr-only">{state === "failed" ? t("copyFailed") : ""}</span>
  </span>;
}

function CopyFeedback({ message }: { message: "copied" | "copyFailed" }) { const { t } = useTranslation("mcp"); return t(message); }
