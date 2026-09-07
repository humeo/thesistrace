import { Copy, Check } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
export function CopyButton({ text, label, primary = false }: { text: string; label: string; primary?: boolean }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  return <span className="mcp-copy-control">
    <button type="button" className={primary ? "mcp-primary" : undefined} onClick={async () => {
      clearTimeout(timer.current);
      try { await navigator.clipboard.writeText(text); setState("copied"); }
      catch { setState("failed"); }
      timer.current = setTimeout(() => setState("idle"), 2500);
    }}>{state === "copied" ? <Check size={15} /> : <Copy size={15} />}{state === "copied" ? "Copied" : label}</button>
    <span role="status">{state === "failed" ? "Copy failed. Select and copy the text manually." : ""}</span>
  </span>;
}
