import { type KeyboardEvent, useEffect, useRef, useState } from "react";

import { OperatorPageNotFoundError } from "./operatorDirectoryClient";
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
  const dialog = useRef<HTMLDialogElement | null>(null);
  const request = useRef<AbortController | null>(null);
  const [email, setEmail] = useState(initialEmail);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
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
        password,
        controller.signal,
      );
      setPassword("");
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
      setPassword("");
      request.current = null;
      setSubmitting(false);
    }
  }

  function containKeyboardFocus(event: KeyboardEvent<HTMLDialogElement>): void {
    if (event.key !== "Tab") return;
    const element = dialog.current;
    if (element === null) return;
    const targets = Array.from(
      element.querySelectorAll<HTMLElement>(
        "input:not(:disabled), button:not(:disabled)",
      ),
    );
    const first = targets[0];
    const last = targets.at(-1);
    if (first === undefined || last === undefined) {
      event.preventDefault();
      return;
    }
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
      return;
    }
    if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
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
      onKeyDown={containKeyboardFocus}
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
          <p className="eyebrow">Password confirmation</p>
          <h2 id="operator-invitation-title">
            {reissue ? "Reissue Invitation?" : "Issue Invitation?"}
          </h2>
        </header>
        <p id="operator-invitation-description">
          {reissue
            ? "Confirm the exact replacement before Auth invalidates the old link."
            : "Confirm the exact recipient before Auth sends an invite-only access link."}
        </p>
        <label className="operator-confirmation-field">
          <span>Target email</span>
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
          <span>Effect</span>
          <p>
            {reissue
              ? "A new link will be sent. The old link becomes invalid only after delivery succeeds."
              : "A 48-hour Invitation will be delivered using the existing invite-only rules."}
          </p>
        </div>
        <label className="operator-confirmation-field">
          <span>Current password</span>
          <input
            autoComplete="current-password"
            disabled={submitting}
            maxLength={128}
            minLength={12}
            onChange={(event) => setPassword(event.target.value)}
            required
            type="password"
            value={password}
          />
        </label>
        {error === null ? null : (
          <p className="inline-status inline-status-error" role="alert">{error}</p>
        )}
        <footer className="operator-confirmation-actions">
          <button
            disabled={submitting}
            onClick={() => onDismiss()}
            type="button"
          >
            Cancel
          </button>
          <button className="button-primary" disabled={submitting} type="submit">
            {submitting
              ? reissue ? "Reissuing…" : "Sending…"
              : reissue ? "Reissue Invitation" : "Send Invitation"}
          </button>
        </footer>
      </form>
    </dialog>
  );
}

function operatorMutationMessage(reason: unknown, reissue: boolean): string {
  if (reason instanceof OperatorPageNotFoundError) {
    return "Operator access is no longer available.";
  }
  if (!(reason instanceof OperatorMutationError)) {
    return "Invitation could not be completed. Try again.";
  }
  if (reason.code === "invalid-password") return "Current password is incorrect.";
  if (reason.code === "invalid-proof") {
    return "Confirmation expired or was already used. Submit again.";
  }
  if (reason.code === "conflict") {
    return "A Researcher or effective Invitation already exists for this email.";
  }
  if (reason.code === "delivery-failed") {
    return reissue
      ? "Delivery failed. The previous Invitation remains valid."
      : "Delivery failed. No effective Invitation was created.";
  }
  if (reason.code === "rate-limited") {
    return "Too many confirmation attempts. Wait one minute and try again.";
  }
  if (reason.code === "request-invalid") {
    return "Enter a valid canonical email and try again.";
  }
  return "Invitation service is unavailable. Try again.";
}
