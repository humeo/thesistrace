import type { ReactNode } from "react";
import { Info } from "@phosphor-icons/react";
import { Button } from "../components/ui/button";
import { Popover, PopoverContent, PopoverTitle, PopoverTrigger } from "../components/ui/popover";
import { useTranslation } from "../i18n";

export function ResearchInfotip({ label, buttonLabel, children }: { label: string; buttonLabel?: string; children: ReactNode }) {
  const { t } = useTranslation("research");
  return <Popover>
    <PopoverTrigger openOnHover delay={300} closeDelay={100}
      render={<Button variant="ghost" size="icon-sm" className="research-infotip-trigger" aria-label={buttonLabel ?? t("helpAbout", { label })} />}>
      <Info aria-hidden="true" />
    </PopoverTrigger>
    <PopoverContent side="bottom" align="start" className="research-infotip-content w-[min(320px,calc(100vw-32px))] text-sm">
      <PopoverTitle>{label}</PopoverTitle>
      <div className="leading-relaxed text-muted-foreground">{children}</div>
    </PopoverContent>
  </Popover>;
}
