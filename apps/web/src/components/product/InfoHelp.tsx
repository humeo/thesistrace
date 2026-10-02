import type { ReactNode } from "react";
import { Info, X } from "@phosphor-icons/react";
import { cn } from "cn";
import { Button } from "../ui/button";
import { Popover, PopoverClose, PopoverContent, PopoverTitle, PopoverTrigger } from "../ui/popover";

export function InfoHelp({ label, buttonLabel, closeLabel, className, children }: {
  label: string;
  buttonLabel?: string;
  closeLabel?: string;
  className?: string;
  children: ReactNode;
}) {
  return <Popover>
    <PopoverTrigger openOnHover delay={300} closeDelay={100}
      render={<Button variant="ghost" size="icon-xs" className={cn("info-help-trigger", className)} aria-label={buttonLabel ?? label} aria-description={typeof children === "string" ? children : undefined} />}>
      <Info aria-hidden="true" />
    </PopoverTrigger>
    <PopoverContent side="bottom" align="start" className="console-workspace max-h-[calc(100dvh-24px)] w-[min(320px,calc(100vw-32px))] gap-1 overflow-y-auto px-3.5 py-3">
      <div className="flex items-start justify-between gap-3">
        <PopoverTitle>{label}</PopoverTitle>
        {closeLabel && <PopoverClose render={<Button variant="ghost" size="icon-xs" aria-label={closeLabel} />}><X aria-hidden="true" /></PopoverClose>}
      </div>
      <div className="text-sm text-muted-foreground [overflow-wrap:anywhere]">{children}</div>
    </PopoverContent>
  </Popover>;
}
