import { useTranslation } from "react-i18next";
import { Button } from "../components/ui/button";

export function ResearchFolderLoadFailure({
  error,
  onRetry,
}: {
  error: "folderError";
  onRetry: () => void;
}) {
  const { t } = useTranslation("runs");
  return (
    <section aria-label={t("folderAvailability")}>
      <p role="alert">{t(error)}</p>
      <Button variant="outline" onClick={onRetry}>{t("retryFolders")}</Button>
    </section>
  );
}

