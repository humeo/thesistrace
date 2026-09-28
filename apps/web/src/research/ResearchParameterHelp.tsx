import type { ReactNode } from "react";
import { Info } from "@phosphor-icons/react";
import { useTranslation } from "../i18n";
import { Button } from "../components/ui/button";
import { Popover, PopoverContent, PopoverTitle, PopoverTrigger } from "../components/ui/popover";

export function ResearchParameterHelp({ helpId, text }: { helpId: "cash" | "weighting" | "volatility" | "exposure" | "universe"; text: ReactNode }) {
  const { t } = useTranslation("research");
  return <Popover>
    <PopoverTrigger render={<Button variant="ghost" size="icon-sm" aria-label={t(`helpLabels.${helpId}`)} />}>
      <Info aria-hidden="true" />
    </PopoverTrigger>
    <PopoverContent className="w-[min(360px,calc(100vw-32px))] max-h-[min(70dvh,var(--available-height))] overflow-y-auto text-sm">
      <PopoverTitle>{t(`helpLabels.${helpId}`)}</PopoverTitle>
      {text}
    </PopoverContent>
  </Popover>;
}
