import type { ReactNode } from "react";
import { InfoHelp } from "../components/product/InfoHelp";
import { useTranslation } from "../i18n";

export function ResearchInfotip({ label, buttonLabel, children }: { label: string; buttonLabel?: string; children: ReactNode }) {
  const { t } = useTranslation("research");
  return <InfoHelp label={label} buttonLabel={buttonLabel ?? t("helpAbout", { label })} className="research-infotip-trigger">{children}</InfoHelp>;
}
