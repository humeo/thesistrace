import { useTranslation } from "../i18n";

export function OperatorConsoleNavigation({
  current,
}: Readonly<{
  current: "data" | "researchers";
}>) {
  const { t } = useTranslation("operator");
  return (
    <nav aria-label={t("researchers.navigation.sections")} className="operator-subnav">
      <a
        aria-current={current === "researchers" ? "page" : undefined}
        href="/operator/researchers"
      >
        {t("researchers.navigation.researchers")}
      </a>
      <a
        aria-current={current === "data" ? "page" : undefined}
        href="/operator/data"
      >
        {t("researchers.navigation.data")}
      </a>
    </nav>
  );
}
