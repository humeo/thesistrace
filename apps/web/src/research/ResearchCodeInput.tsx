import { Suspense, type ReactNode } from "react";
import { InputGroup } from "../components/ui/input-group";
import { useTranslation } from "../i18n";

/** Shared surface for Alpha and exposure CodeMirror inputs. */
export function ResearchCodeInput({ children, height = 180 }: {
  children: ReactNode; height?: number;
}) {
  const { t } = useTranslation("common");
  return <InputGroup className="resize-y overflow-hidden focus-within:border-ring focus-within:ring-2 focus-within:ring-ring/30"
    style={{ height, minHeight: 180 }}>
    <Suspense fallback={<p role="status" className="p-3 text-sm text-muted-foreground">{t("loadingWorkspace")}</p>}>{children}</Suspense>
  </InputGroup>;
}
