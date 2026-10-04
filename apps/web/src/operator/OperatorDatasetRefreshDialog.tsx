import { useRef } from "react";
import { useTranslation } from "../i18n";

import { OperatorPageNotFoundError } from "./operatorDirectoryClient";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../components/ui/dialog";
import { Button } from "../components/ui/button";
import { Alert, AlertDescription } from "../components/ui/alert";
import { operatorDataClasses as styles } from "./operatorDataClasses";
import {
  type DatasetRefreshRequest,
  OperatorMutationError,
} from "./operatorMutationClient";

export function OperatorDatasetRefreshDialog({ onDismiss, onSubmit, submitting, error, request: refreshRequest }: Readonly<{
  onDismiss: () => void;
  onSubmit: () => Promise<void>;
  submitting: boolean;
  error: unknown | null;
  request: DatasetRefreshRequest;
}>) {
  const { t } = useTranslation("operator");
  const initialFocus = useRef<HTMLButtonElement | null>(null);

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onDismiss(); }}>
      <DialogContent finalFocus={false} initialFocus={initialFocus} showCloseButton={false} className="max-h-[calc(100dvh-32px)] overflow-y-auto sm:max-w-lg">
        <form className={styles.confirmationForm} onSubmit={(event) => { event.preventDefault(); void onSubmit(); }}>
          <DialogHeader>
            <p className={styles.eyebrow}>{t("data.common.confirmUpdate")}</p>
            <DialogTitle id="operator-market-refresh-title">{t("data.dataset.submitTitle")}</DialogTitle>
          </DialogHeader>
          <DialogDescription id="operator-market-refresh-description">{t("data.dataset.submitDescription")}</DialogDescription>
          <dl className={styles.target}>
            <div><dt>{t("data.common.kind")}</dt><dd><strong>{t("data.dataset.kind")}</strong></dd></div>
            <div><dt>{t("data.common.asOf")}</dt><dd><code>{refreshRequest.asOf}</code></dd></div>
            <div><dt>{t("data.common.idempotencyKey")}</dt><dd><code>{refreshRequest.idempotencyKey}</code></dd></div>
          </dl>
          <Alert role="note"><AlertDescription><strong>{t("data.common.effect")}</strong><p>{t("data.dataset.effect")}</p></AlertDescription></Alert>
          {error === null ? null : <Alert variant="destructive" role="alert"><AlertDescription>{t(datasetRefreshMutationMessage(error))}</AlertDescription></Alert>}
          <DialogFooter>
            <Button variant="outline" onClick={onDismiss} ref={initialFocus} type="button">{t("data.common.cancel")}</Button>
            <Button disabled={submitting} type="submit">{submitting ? t("data.common.submitting") : t("data.common.submitRefresh")}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function datasetRefreshMutationMessage(reason: unknown) {
  if (reason instanceof OperatorPageNotFoundError) {
    return "data.common.accessLost";
  }
  if (!(reason instanceof OperatorMutationError)) {
    return "data.dataset.submitFailed";
  }
  if (reason.code === "invalid-otp") return "data.common.invalidOtp";
  if (reason.code === "invalid-proof") {
    return "data.common.invalidProof";
  }
  if (reason.code === "data-not-ready") {
    return "data.dataset.dataNotReady";
  }
  if (reason.code === "rate-limited") {
    return "data.common.rateLimited";
  }
  return "data.dataset.unavailable";
}
