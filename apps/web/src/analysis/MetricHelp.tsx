import { Question, X } from "@phosphor-icons/react";
import { useState } from "react";
import { Button } from "../components/ui/button";
import { Popover, PopoverContent, PopoverTitle, PopoverTrigger } from "../components/ui/popover";
import { useTranslation } from "../i18n";

export type MetricHelpContent = Readonly<{
  description: string;
  formula: string;
  range: string;
  direction: string;
  note?: string;
}>;

export function MetricHelp({ label, content }: { label: string; content: MetricHelpContent }) {
  const { t } = useTranslation("analysis");
  const [open, setOpen] = useState(false);
  return <Popover open={open} onOpenChange={setOpen}>
    <PopoverTrigger render={<Button variant="ghost" size="icon-xs" className="size-11 sm:size-7" aria-label={t("help.about", { label })} />}>
      <Question aria-hidden="true" />
    </PopoverTrigger>
    <PopoverContent className="max-h-[calc(100dvh-24px)] w-[min(360px,calc(100vw-24px))] overflow-y-auto p-4" align="end">
      <div className="flex items-start justify-between gap-3">
        <PopoverTitle className="text-sm font-semibold">{label}</PopoverTitle>
        <Button variant="ghost" size="icon-xs" className="size-11 sm:size-7" aria-label={t("help.close")} onClick={() => setOpen(false)}><X aria-hidden="true" /></Button>
      </div>
      <p className="m-0 text-sm leading-[22px] text-muted-foreground">{content.description}</p>
      <dl className="m-0 grid gap-2 text-sm">
        <div><dt className="font-medium">{t("help.formula")}</dt><dd className="m-0 text-muted-foreground">{content.formula}</dd></div>
        <div><dt className="font-medium">{t("help.range")}</dt><dd className="m-0 text-muted-foreground">{content.range}</dd></div>
        <div><dt className="font-medium">{t("help.direction")}</dt><dd className="m-0 text-muted-foreground">{content.direction}</dd></div>
      </dl>
      {content.note ? <p className="m-0 border-t border-border pt-2 text-xs text-muted-foreground">{content.note}</p> : null}
    </PopoverContent>
  </Popover>;
}
