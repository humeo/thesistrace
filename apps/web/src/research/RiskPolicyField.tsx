import type { ReactNode } from "react";
import { Field, FieldGroup, FieldLabel, FieldLegend, FieldSet } from "../components/ui/field";
import { Switch } from "../components/ui/switch";
import { useTranslation } from "../i18n";
import { ResearchInfotip } from "./ResearchInfotip";
import type { RiskPolicy } from "./riskPolicies";

export function RiskPolicyField({ policy, title, help, enabled, onChange, children }: {
  policy: RiskPolicy; title: string; help: ReactNode; enabled: boolean;
  onChange: (enabled: boolean) => void; children: ReactNode;
}) {
  const { t } = useTranslation("strategy");
  const id = `risk-policy-${policy}`;
  return <FieldSet className="m-0 min-w-0 gap-3 border-0 p-0">
    <FieldLegend className="sr-only">{title}</FieldLegend>
    <Field orientation="horizontal" className="min-h-9 gap-1">
      <FieldLabel htmlFor={id}>{title}</FieldLabel>
      <ResearchInfotip label={title}>{help}</ResearchInfotip>
      <span className="ml-auto mr-2 text-xs text-muted-foreground">{t(enabled ? "riskPolicies.enabled" : "riskPolicies.disabled")}</span>
      <Switch id={id} checked={enabled} onCheckedChange={onChange} />
    </Field>
    <FieldGroup hidden={!enabled} className={!enabled ? "hidden" : "gap-4"}>{children}</FieldGroup>
  </FieldSet>;
}
