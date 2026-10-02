import { useState, type ReactNode } from "react";
import { CaretDown } from "@phosphor-icons/react";
import { Button } from "../components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../components/ui/collapsible";

export function RuleDisclosure({ title, description, configured = false, invalid = false, children }: {
  title: string; description?: string; configured?: boolean; invalid?: boolean; children: ReactNode;
}) {
  const [open, setOpen] = useState(configured);
  return <Collapsible open={open || invalid} onOpenChange={setOpen} className="min-w-0 border-t border-border pt-3">
    <CollapsibleTrigger render={<Button variant="ghost" className="h-auto min-h-10 w-full justify-between whitespace-normal px-0 text-left" />}>
      {title}<CaretDown data-icon="inline-end" aria-hidden="true" />
    </CollapsibleTrigger>
    {description && !open && !invalid && <p className="rule-disclosure-description m-0 text-xs text-muted-foreground">{description}</p>}
    <CollapsibleContent keepMounted className="min-w-0 pt-3">{children}</CollapsibleContent>
  </Collapsible>;
}
