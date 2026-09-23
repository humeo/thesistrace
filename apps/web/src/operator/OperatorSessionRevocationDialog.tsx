import { OperatorCodeField } from "./OperatorCodeField";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "../i18n";
import { formatNumber } from "../i18n/format";

import { OperatorPageNotFoundError } from "./operatorDirectoryClient";
import { containDialogKeyboardFocus } from "./operatorDialog";
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
  const dialog = useRef<HTMLDialogElement | null>(null);
  const request = useRef<AbortController | null>(null);
  const [otp, setOtp] = useState("");
  const [error, setError] = useState<ReturnType<typeof sessionRevocationMessage> | null>(null);
  const [submitting, setSubmitting] = useState(false);

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
    <dialog
      aria-describedby="operator-session-revocation-description"
      aria-labelledby="operator-session-revocation-title"
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
          <p className="eyebrow operator-danger-eyebrow">{t("researchers.session.eyebrow")}</p>
          <h2 id="operator-session-revocation-title">{t("researchers.session.title")}</h2>
        </header>
        <p id="operator-session-revocation-description">
          {t("researchers.session.description")}
        </p>
        <dl className="operator-confirmation-target">
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
        <div className="operator-confirmation-effect operator-confirmation-effect-danger">
          <span>{t("researchers.common.effect")}</span>
          <p>{t("researchers.session.effect")}</p>
        </div>
        <OperatorCodeField value={otp} onChange={setOtp} disabled={submitting} />
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
          <button className="button-danger" disabled={submitting} type="submit">
            {submitting ? t("researchers.session.revoking") : t("researchers.session.revoke")}
          </button>
        </footer>
      </form>
    </dialog>
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
