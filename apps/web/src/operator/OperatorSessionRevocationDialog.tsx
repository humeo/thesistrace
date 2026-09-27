import { OperatorCodeField } from "./OperatorCodeField";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "../i18n";
import { formatNumber } from "../i18n/format";

import { OperatorPageNotFoundError } from "./operatorDirectoryClient";
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter } from "../components/ui/alert-dialog";
import { Button } from "../components/ui/button";
import { Alert, AlertDescription } from "../components/ui/alert";
import { FieldGroup } from "../components/ui/field";
import styles from "./OperatorAccess.module.css";
import {
  confirmSessionRevocationProof,
  OperatorMutationError,
  submitSessionRevocation,
} from "./operatorMutationClient";

export type SessionRevocationTarget = Readonly<{
  currentSessionCount: number;
  displayLabel: string;
  email: string;
  researcherId: string;
}>;

export function OperatorSessionRevocationDialog({
  onDismiss,
  onSucceeded,
  target,
}: Readonly<{
  onDismiss: () => void;
  onSucceeded: (result: Readonly<{
    researcherId: string;
    revokedSessionCount: number;
  }>) => void;
  target: SessionRevocationTarget;
}>) {
  const { t } = useTranslation("operator");
  const initialInput = useRef<HTMLInputElement>(null);
  const request = useRef<AbortController | null>(null);
  const [otp, setOtp] = useState("");
  const [error, setError] = useState<ReturnType<typeof sessionRevocationMessage> | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => () => {
    request.current?.abort();
    request.current = null;
  }, []);

  async function submit(): Promise<void> {
    if (submitting) return;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setSubmitting(true);
    setError(null);
    try {
      const confirmed = await confirmSessionRevocationProof(
        target.researcherId,
        otp,
        controller.signal,
      );
      setOtp("");
      const result = await submitSessionRevocation(
        target.researcherId,
        confirmed.proof,
        controller.signal,
      );
      onSucceeded(result);
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      setError(sessionRevocationMessage(reason));
    } finally {
      setOtp("");
      request.current = null;
      setSubmitting(false);
    }
  }

  return (
    <AlertDialog open onOpenChange={open => { if (!open && !submitting) onDismiss(); }}>
      <AlertDialogContent finalFocus={false} initialFocus={initialInput}  className="max-h-[calc(100dvh-32px)] overflow-y-auto sm:max-w-lg">
      <form
        className={styles.form}
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <FieldGroup>
        <AlertDialogHeader>
          <p className={styles.eyebrow}>{t("researchers.session.eyebrow")}</p>
          <AlertDialogTitle id="operator-session-revocation-title">{t("researchers.session.title")}</AlertDialogTitle>
        </AlertDialogHeader>
        <AlertDialogDescription id="operator-session-revocation-description">
          {t("researchers.session.description")}
        </AlertDialogDescription>
        <dl className={styles.target}>
          <div>
            <dt>{t("researchers.session.researcher")}</dt>
            <dd><strong>{target.displayLabel}</strong><span>{target.email}</span></dd>
          </div>
          <div>
            <dt>{t("researchers.session.researcherId")}</dt>
            <dd><code>{target.researcherId}</code></dd>
          </div>
          <div>
            <dt>{t("researchers.session.current")}</dt>
            <dd><strong>{formatNumber(target.currentSessionCount)}</strong></dd>
          </div>
        </dl>
        <Alert variant="destructive" role="note">
          <span>{t("researchers.common.effect")}</span>
          <p>{t("researchers.session.effect")}</p>
        </Alert>
        <OperatorCodeField inputRef={initialInput} autoFocus={false} value={otp} onChange={setOtp} disabled={submitting} />
        {error === null ? null : (
          <Alert variant="destructive"><AlertDescription>{t(error)}</AlertDescription></Alert>
        )}
        <AlertDialogFooter>
          <Button variant="outline"
            disabled={submitting}
            onClick={() => onDismiss()}
            type="button"
          >
            {t("researchers.common.cancel")}
          </Button>
          <Button variant="destructive" disabled={submitting} type="submit">
            {submitting ? t("researchers.session.revoking") : t("researchers.session.revoke")}
          </Button>
        </AlertDialogFooter>
        </FieldGroup>
      </form>
    </AlertDialogContent></AlertDialog>
  );
}

function sessionRevocationMessage(reason: unknown) {
  if (reason instanceof OperatorPageNotFoundError) {
    return "researchers.common.accessLost";
  }
  if (!(reason instanceof OperatorMutationError)) {
    return "researchers.session.failed";
  }
  if (reason.code === "invalid-otp") return "researchers.common.invalidOtp";
  if (reason.code === "invalid-proof") {
    return "researchers.common.invalidProof";
  }
  if (reason.code === "protected-target") {
    return "researchers.session.protectedTarget";
  }
  if (reason.code === "invalid-target") {
    return "researchers.session.invalidTarget";
  }
  if (reason.code === "rate-limited") {
    return "researchers.common.rateLimited";
  }
  if (reason.code === "request-invalid") {
    return "researchers.session.requestInvalid";
  }
  return "researchers.session.unavailable";
}
