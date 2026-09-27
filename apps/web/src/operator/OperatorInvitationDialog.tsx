import { OperatorCodeField } from "./OperatorCodeField";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "../i18n";

import { OperatorPageNotFoundError } from "./operatorDirectoryClient";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../components/ui/dialog";
import { Button } from "../components/ui/button";
import { Alert, AlertDescription } from "../components/ui/alert";
import { Field, FieldLabel, FieldGroup } from "../components/ui/field";
import { Input } from "../components/ui/input";
import { operatorAccessLayout } from "./operatorAccessLayout";
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
  const initialInput = useRef<HTMLInputElement>(null);
  const request = useRef<AbortController | null>(null);
  const [email, setEmail] = useState(initialEmail);
  const [otp, setOtp] = useState("");
  const [error, setError] = useState<ReturnType<typeof operatorMutationMessage> | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const canonicalTarget = email.trim().toLowerCase();
  const reissue = operation === "reissue";

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
    <Dialog open onOpenChange={open => { if (!open && !submitting) onDismiss(); }}>
      <DialogContent finalFocus={false} initialFocus={initialInput} showCloseButton={false} className="max-h-[calc(100dvh-32px)] overflow-y-auto sm:max-w-lg">
      <form
        className={operatorAccessLayout.form}
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <FieldGroup>
        <DialogHeader>
          <p className={operatorAccessLayout.eyebrow}>{t("researchers.common.emailConfirmation")}</p>
          <DialogTitle id="operator-invitation-title">
            {reissue ? t("researchers.invitation.reissueTitle") : t("researchers.invitation.issueTitle")}
          </DialogTitle>
        </DialogHeader>
        <DialogDescription id="operator-invitation-description">
          {reissue
            ? t("researchers.invitation.reissueDescription")
            : t("researchers.invitation.issueDescription")}
        </DialogDescription>
        <Field>
          <FieldLabel htmlFor={reissue ? undefined : "operator-invitation-email"}>{t("researchers.common.targetEmail")}</FieldLabel>
          {reissue ? (
            <strong className={operatorAccessLayout.emailTarget}>{canonicalTarget}</strong>
          ) : (
            <Input
              id="operator-invitation-email"
              ref={initialInput}
              autoComplete="email"
              disabled={submitting}
              onChange={(event) => setEmail(event.target.value)}
              required
              type="email"
              value={email}
            />
          )}
        </Field>
        <Alert role="note">
          <span>{t("researchers.common.effect")}</span>
          <p>
            {reissue
              ? t("researchers.invitation.reissueEffect")
              : t("researchers.invitation.issueEffect")}
          </p>
        </Alert>
        <OperatorCodeField inputRef={reissue ? initialInput : undefined} autoFocus={false} value={otp} onChange={setOtp} disabled={submitting} />
        {error === null ? null : (
          <Alert variant="destructive"><AlertDescription>{t(error)}</AlertDescription></Alert>
        )}
        <DialogFooter>
          <Button variant="outline"
            disabled={submitting}
            onClick={() => onDismiss()}
            type="button"
          >
            {t("researchers.common.cancel")}
          </Button>
          <Button disabled={submitting} type="submit">
            {submitting
              ? reissue ? t("researchers.invitation.reissuing") : t("researchers.invitation.sending")
              : reissue ? t("researchers.invitation.reissue") : t("researchers.invitation.send")}
          </Button>
        </DialogFooter>
        </FieldGroup>
      </form>
    </DialogContent></Dialog>
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
