import { InfoHelp } from "../components/product/InfoHelp";
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
  return <InfoHelp label={label} buttonLabel={t("help.about", { label })} closeLabel={t("help.close")}>
    <div className="grid gap-3">
      <p className="m-0 text-sm text-muted-foreground">{content.description}</p>
      <dl className="m-0 grid gap-2 text-sm">
        <div><dt className="font-medium">{t("help.formula")}</dt><dd className="m-0 text-muted-foreground">{content.formula}</dd></div>
        <div><dt className="font-medium">{t("help.range")}</dt><dd className="m-0 text-muted-foreground">{content.range}</dd></div>
        <div><dt className="font-medium">{t("help.direction")}</dt><dd className="m-0 text-muted-foreground">{content.direction}</dd></div>
      </dl>
      {content.note ? <p className="m-0 border-t border-border pt-2 text-xs text-muted-foreground">{content.note}</p> : null}
    </div>
  </InfoHelp>;
}
