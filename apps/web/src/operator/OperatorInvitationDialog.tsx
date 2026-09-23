import { OperatorCodeField } from "./OperatorCodeField";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "../i18n";

import { OperatorPageNotFoundError } from "./operatorDirectoryClient";
import { containDialogKeyboardFocus } from "./operatorDialog";
import {
  confirmOperatorProof,
  type InvitationMutationOperation,
  OperatorMutationError,
  submitInvitationMutation,
} from "./operatorMutationClient";

export function OperatorInvitationDialog({
  email: initialEmail,
  onDismiss,
  onSucceeded,
  operation,
}: Readonly<{
  email: string;
  onDismiss: () => void;
  onSucceeded: (result: Readonly<{
    email: string;
    operation: InvitationMutationOperation;
  }>) => void;
  operation: InvitationMutationOperation;
}>) {
  const { t } = useTranslation("operator");
  const dialog = useRef<HTMLDialogElement | null>(null);
  const request = useRef<AbortController | null>(null);
  const [email, setEmail] = useState(initialEmail);
  const [otp, setOtp] = useState("");
  const [error, setError] = useState<ReturnType<typeof operatorMutationMessage> | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const canonicalTarget = email.trim().toLowerCase();
  const reissue = operation === "reissue";

  useEffect(() => {
    const element = dialog.current;
    if (element === null) return;
    element.showModal();
    return () => {
      request.current?.abort();
      request.current = null;
      if (element.open) element.close();
    };
  }, []);

  async function submit(): Promise<void> {
    if (submitting) return;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setSubmitting(true);
    setError(null);
    try {
      const confirmed = await confirmOperatorProof(
        operation,
        email,
        otp,
        controller.signal,
      );
      setOtp("");
      const result = await submitInvitationMutation(
        operation,
        email,
        confirmed.proof,
        controller.signal,
      );
      onSucceeded({ email: result.email, operation });
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      setError(operatorMutationMessage(reason, reissue));
    } finally {
      setOtp("");
      request.current = null;
      setSubmitting(false);
    }
  }

  return (
    <dialog
      aria-describedby="operator-invitation-description"
      aria-labelledby="operator-invitation-title"
      aria-modal="true"
      className="operator-confirmation-dialog"
      onCancel={(event) => {
        event.preventDefault();
        if (!submitting) onDismiss();
      }}
      onKeyDown={(event) => containDialogKeyboardFocus(event, dialog.current)}
      ref={dialog}
    >
      <form
        className="operator-confirmation-content"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <header>
          <p className="eyebrow">{t("researchers.common.emailConfirmation")}</p>
          <h2 id="operator-invitation-title">
            {reissue ? t("researchers.invitation.reissueTitle") : t("researchers.invitation.issueTitle")}
          </h2>
        </header>
        <p id="operator-invitation-description">
          {reissue
            ? t("researchers.invitation.reissueDescription")
            : t("researchers.invitation.issueDescription")}
        </p>
        <label className="operator-confirmation-field">
          <span>{t("researchers.common.targetEmail")}</span>
          {reissue ? (
            <strong>{canonicalTarget}</strong>
          ) : (
            <input
              autoComplete="email"
              disabled={submitting}
              onChange={(event) => setEmail(event.target.value)}
              required
              type="email"
              value={email}
            />
          )}
        </label>
        <div className="operator-confirmation-effect">
          <span>{t("researchers.common.effect")}</span>
          <p>
            {reissue
              ? t("researchers.invitation.reissueEffect")
              : t("researchers.invitation.issueEffect")}
          </p>
        </div>
        <OperatorCodeField autoFocus={false} value={otp} onChange={setOtp} disabled={submitting} />
        {error === null ? null : (
          <p className="inline-status inline-status-error" role="alert">{t(error)}</p>
        )}
        <footer className="operator-confirmation-actions">
          <button
            disabled={submitting}
            onClick={() => onDismiss()}
            type="button"
          >
            {t("researchers.common.cancel")}
          </button>
          <button className="button-primary" disabled={submitting} type="submit">
            {submitting
              ? reissue ? t("researchers.invitation.reissuing") : t("researchers.invitation.sending")
              : reissue ? t("researchers.invitation.reissue") : t("researchers.invitation.send")}
          </button>
        </footer>
      </form>
    </dialog>
  );
}

function operatorMutationMessage(reason: unknown, reissue: boolean) {
  if (reason instanceof OperatorPageNotFoundError) {
    return "researchers.common.accessLost";
  }
  if (!(reason instanceof OperatorMutationError)) {
    return "researchers.invitation.failed";
  }
  if (reason.code === "invalid-otp") return "researchers.common.invalidOtp";
  if (reason.code === "invalid-proof") {
    return "researchers.common.invalidProof";
  }
  if (reason.code === "conflict") {
    return "researchers.invitation.conflict";
  }
  if (reason.code === "delivery-failed") {
    return reissue
      ? "researchers.invitation.deliveryFailedReissue"
      : "researchers.invitation.deliveryFailedIssue";
  }
  if (reason.code === "rate-limited") {
    return "researchers.common.rateLimited";
  }
  if (reason.code === "request-invalid") {
    return "researchers.invitation.requestInvalid";
  }
  return "researchers.invitation.unavailable";
}
