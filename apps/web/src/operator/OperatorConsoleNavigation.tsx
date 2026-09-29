import { useTranslation } from "../i18n";

import { Button } from "../components/ui/button";

export function OperatorConsoleNavigation({
  current,
}: Readonly<{
  current: "data" | "researchers";
}>) {
  const { t } = useTranslation("operator");
  return (
    <nav aria-label={t("researchers.navigation.sections")} className="flex flex-wrap gap-6 border-b border-border">
      <Button variant="navigation" size="xl" nativeButton={false} role="link" render={<a aria-current={current === "researchers" ? "page" : undefined} href="/operator/researchers" />} >
        {t("researchers.navigation.researchers")}
      </Button>
      <Button variant="navigation" size="xl" nativeButton={false} role="link" render={<a aria-current={current === "data" ? "page" : undefined} href="/operator/data" />} >
        {t("researchers.navigation.data")}
      </Button>
    </nav>
  );
}
