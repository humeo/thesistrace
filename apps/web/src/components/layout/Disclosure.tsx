import type { ReactNode } from "react";
import { CaretDown, CaretRight } from "@phosphor-icons/react";
import { cn } from "cn";
import { Button } from "../ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../ui/collapsible";

/** A secondary section with a consistent keyboard and touch target. */
export function Disclosure({ title, children, className, variant = "panel", open, onOpenChange }: {
  title: ReactNode;
  children: ReactNode;
  className?: string;
  variant?: "panel" | "row";
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  return <Collapsible open={open} onOpenChange={onOpenChange} className={cn("col-span-full min-w-0", variant === "row" ? "border-b border-border last:border-b-0" : "rounded-lg border border-border bg-card", className)}>
    <CollapsibleTrigger render={<Button variant="ghost" className={cn("group/disclosure h-auto w-full justify-between whitespace-normal text-left", variant === "row" ? "min-h-9 rounded-none px-5 py-1.5" : "min-h-11 p-3")} />}>
      {title}{variant === "row" ? <CaretRight aria-hidden="true" data-icon="inline-end" className="transition-transform group-aria-expanded/disclosure:rotate-90" /> : <CaretDown aria-hidden="true" data-icon="inline-end" />}
    </CollapsibleTrigger>
    <CollapsibleContent keepMounted className={cn("min-w-0 pb-4 text-sm leading-[22px] [overflow-wrap:anywhere]", variant === "row" ? "px-5" : "px-4")}>
      {children}
    </CollapsibleContent>
  </Collapsible>;
}
