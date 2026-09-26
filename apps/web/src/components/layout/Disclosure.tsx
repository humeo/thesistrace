import type { ReactNode } from "react";
import { CaretDown } from "@phosphor-icons/react";
import { cn } from "cn";
import { Button } from "../ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../ui/collapsible";

/** A secondary section with a consistent keyboard and touch target. */
export function Disclosure({ title, children, className }: {
  title: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return <Collapsible className={cn("col-span-full min-w-0 rounded-lg border border-border bg-card", className)}>
    <CollapsibleTrigger render={<Button variant="ghost" className="h-auto min-h-11 w-full justify-between whitespace-normal p-3 text-left" />}>
      {title}<CaretDown aria-hidden="true" data-icon="inline-end" />
    </CollapsibleTrigger>
    <CollapsibleContent keepMounted className="min-w-0 px-4 pb-4 text-sm leading-[22px] [overflow-wrap:anywhere]">
      {children}
    </CollapsibleContent>
  </Collapsible>;
}
