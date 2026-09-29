import type { ReactNode } from "react";
import { cn } from "cn";

export function MetricGroup({ children, className, label, variant = "default" }: {
  children: ReactNode;
  className?: string;
  label: string;
  variant?: "default" | "result";
}) {
  return <dl aria-label={label} role="group" className={cn(
    "grid min-w-0 overflow-hidden border border-border bg-card",
    variant === "result" ? "m-0 grid-cols-6 rounded-md px-2 py-4 [container-type:inline-size]" : "grid-cols-2 rounded-lg sm:grid-cols-4",
    className,
  )}>{children}</dl>;
}

export function Metric({ label, value, help, detail, variant = "default", tone }: {
  label: string;
  value: string;
  help?: ReactNode;
  detail?: ReactNode;
  variant?: "default" | "result";
  tone?: "positive" | "negative" | "benchmark";
}) {
  return <div className={cn("min-w-0 border-r border-border last:border-r-0", variant === "result" ? "px-4" : "border-b p-4 sm:border-b-0")}>
    <dt className={cn("flex min-w-0 items-center gap-1", variant === "result" ? "min-h-7 text-base leading-6 text-foreground" : "text-xs leading-[18px] text-muted-foreground")}>
      <span className="min-w-0 [overflow-wrap:anywhere]">{label}</span>{help}
    </dt>
    <dd className={cn("m-0 tabular-nums", variant === "result" ? "mt-1 font-sans text-[clamp(24px,2.25cqw,28px)] leading-9 font-normal whitespace-nowrap" : "mt-2 font-mono text-xl leading-7 font-semibold [overflow-wrap:anywhere]",
      tone === "positive" ? "text-[var(--success)]" : tone === "negative" ? "text-destructive" : tone === "benchmark" ? "text-[var(--benchmark-foreground)]" : "text-foreground",
    )}>{value}</dd>
    {detail ? <p className="m-0 mt-2 text-xs leading-[18px] text-muted-foreground">{detail}</p> : null}
  </div>;
}
