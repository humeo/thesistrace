import type { ReactNode } from "react";
import { Info } from "@phosphor-icons/react";
import { Button } from "../ui/button";
import { Popover, PopoverContent, PopoverTitle, PopoverTrigger } from "../ui/popover";

export function InfoHelp({ label, children }: { label: string; children: ReactNode }) {
  return <Popover><PopoverTrigger openOnHover delay={300} closeDelay={100} render={<Button variant="ghost" size="icon-xs" aria-label={label} aria-description={typeof children === "string" ? children : undefined} />}><Info aria-hidden="true" /></PopoverTrigger>
    <PopoverContent className="console-workspace w-80 max-w-[calc(100vw-32px)] p-4" align="end"><PopoverTitle>{label}</PopoverTitle><div className="text-sm leading-6 text-muted-foreground [overflow-wrap:anywhere]">{children}</div></PopoverContent>
  </Popover>;
}
