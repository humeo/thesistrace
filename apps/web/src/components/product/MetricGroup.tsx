import type { ReactNode } from "react";
import { cn } from "cn";

export function MetricGroup({ children, className, label }: {
  children: ReactNode;
  className?: string;
  label: string;
}) {
  return <dl aria-label={label} role="group" className={cn("grid min-w-0 grid-cols-2 overflow-hidden rounded-lg border border-border bg-card sm:grid-cols-4", className)}>{children}</dl>;
}

export function Metric({ label, value, help, detail }: {
  label: string;
  value: string;
  help?: ReactNode;
  detail?: ReactNode;
}) {
  return <div className="min-w-0 border-b border-r border-border p-4 last:border-r-0 sm:border-b-0">
    <dt className="flex min-w-0 items-center gap-1 text-xs leading-[18px] text-muted-foreground">
      <span className="min-w-0 [overflow-wrap:anywhere]">{label}</span>{help}
    </dt>
    <dd className="m-0 mt-2 font-mono text-xl leading-7 font-semibold tabular-nums text-foreground [overflow-wrap:anywhere]">{value}</dd>
    {detail ? <p className="m-0 mt-2 text-xs leading-[18px] text-muted-foreground">{detail}</p> : null}
  </div>;
}
