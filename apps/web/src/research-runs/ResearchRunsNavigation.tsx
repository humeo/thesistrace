import { useTranslation } from "react-i18next";
import { followCoreLink } from "../shell/navigation";

export function ResearchRunsNavigation({ active }: { active: "runs" | "batches" }) {
  const { t } = useTranslation("runs");
  return (
    <nav aria-label={t("history")} className="research-history-navigation">
      <a aria-current={active === "runs" ? "page" : undefined} href="/research-runs" onClick={followCoreLink}>{t("runs")}</a>
      <a aria-current={active === "batches" ? "page" : undefined} href="/research-runs/batches" onClick={followCoreLink}>{t("batches")}</a>
    </nav>
  );
}
