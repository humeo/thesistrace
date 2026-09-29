import { useTranslation } from "react-i18next";
import { followCoreLink } from "../shell/navigation";
import { Button } from "../components/ui/button";

export function ResearchRunsNavigation({ active }: { active: "runs" | "batches" }) {
  const { t } = useTranslation("runs");
  return (
    <nav aria-label={t("history")} className="flex flex-wrap gap-6 border-b border-border">
      <Button variant="navigation" size="xl" nativeButton={false} role="link" render={<a aria-current={active === "runs" ? "page" : undefined} href="/research-runs" onClick={followCoreLink} />}>{t("runs")}</Button>
      <Button variant="navigation" size="xl" nativeButton={false} role="link" render={<a aria-current={active === "batches" ? "page" : undefined} href="/research-runs/batches" onClick={followCoreLink} />}>{t("batches")}</Button>
    </nav>
  );
}
