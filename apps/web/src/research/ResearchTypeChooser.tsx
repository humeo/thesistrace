import { ArrowRight, ChartBar, ChartLineUp } from "@phosphor-icons/react";
import { useEffect, useRef, type ReactNode } from "react";

import { PageContent, PageHeader } from "../components/layout/Page";
import { Button } from "../components/ui/button";
import { useTranslation } from "../i18n";
import type { ResearchDraft } from "./draft";

export function ResearchTypeChooser({ onChoose, storageError, folderNavigation }: {
  onChoose: (kind: ResearchDraft["researchKind"]) => void;
  storageError: "failed" | "accepted" | null;
  folderNavigation?: ReactNode;
}) {
  const { t } = useTranslation("research");
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus(); }, []);
  return (
    <section aria-label={t("newResearch")}>
      <PageContent width="wide">
        <PageHeader title={t("newResearch")} actions={folderNavigation} />
        <div className="mx-auto mt-24 grid w-full max-w-[880px] gap-8" aria-labelledby="research-type-heading">
          <div className="grid gap-2">
            <h2 ref={heading} id="research-type-heading" tabIndex={-1} className="m-0 text-xl leading-7 font-semibold outline-none">{t("entry.title")}</h2>
            <p className="m-0 text-sm text-muted-foreground">{t("entry.description")}</p>
          </div>
          <div className="grid grid-cols-2 gap-6">
            {(["factor_evaluation", "strategy_backtest"] as const).map(kind => {
              const Icon = kind === "factor_evaluation" ? ChartBar : ChartLineUp;
              return (
                <Button key={kind} variant="choice" size="choice" className="w-full" type="button"
                  aria-labelledby={`research-choice-${kind}`} aria-describedby={`research-description-${kind}`}
                  onClick={() => onChoose(kind)}>
                  <Icon data-slot="choice-icon" aria-hidden="true" className="size-10" weight="light" />
                  <span className="grid gap-3">
                    <span id={`research-choice-${kind}`} className="text-xl leading-7 font-semibold">{t(kind)}</span>
                    <span id={`research-description-${kind}`} className="text-sm leading-6 font-normal text-muted-foreground">{t(`entry.${kind}`)}</span>
                  </span>
                  <ArrowRight data-slot="choice-arrow" aria-hidden="true" className="absolute top-8 right-8 size-5" />
                </Button>
              );
            })}
          </div>
          {storageError !== null && <p role="alert" className="m-0 text-sm text-destructive">{t(`storage.${storageError}`)}</p>}
        </div>
      </PageContent>
    </section>
  );
}
