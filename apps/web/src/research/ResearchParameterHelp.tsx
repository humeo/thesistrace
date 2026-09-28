import type { ReactNode } from "react";
import { useTranslation } from "../i18n";
import { ResearchInfotip } from "./ResearchInfotip";

export function ResearchParameterHelp({ helpId, text }: { helpId: "cash" | "weighting" | "volatility" | "exposure" | "universe"; text: ReactNode }) {
  const { t } = useTranslation("research");
  return <ResearchInfotip label={t(`helpLabels.${helpId}`)} buttonLabel={t(`helpLabels.${helpId}`)}>{text}</ResearchInfotip>;
}
