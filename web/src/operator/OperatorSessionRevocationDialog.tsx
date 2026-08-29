import { type KeyboardEvent, useEffect, useRef, useState } from "react";

import { OperatorPageNotFoundError } from "./operatorDirectoryClient";
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
  const dialog = useRef<HTMLDialogElement | null>(null);
  const request = useRef<AbortController | null>(null);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
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
        password,
        controller.signal,
      );
      setPassword("");
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
      aria-describedby="operator-session-revocation-description"
      aria-labelledby="operator-session-revocation-title"
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
          <p className="eyebrow operator-danger-eyebrow">Session revocation</p>
          <h2 id="operator-session-revocation-title">Revoke Login Sessions?</h2>
        </header>
        <p id="operator-session-revocation-description">
          Confirm the exact Researcher before removing every current Login Session.
        </p>
        <dl className="operator-confirmation-target">
          <div>
            <dt>Researcher</dt>
            <dd><strong>{target.displayLabel}</strong><span>{target.email}</span></dd>
          </div>
          <div>
            <dt>Researcher ID</dt>
            <dd><code>{target.researcherId}</code></dd>
          </div>
          <div>
            <dt>Current Login Sessions</dt>
            <dd><strong>{target.currentSessionCount}</strong></dd>
          </div>
        </dl>
        <div className="operator-confirmation-effect operator-confirmation-effect-danger">
          <span>Effect</span>
          <p>
            Every current Login Session for this Researcher will be revoked. The
            Researcher remains active and can sign in again.
          </p>
        </div>
        <label className="operator-confirmation-field">
          <span>Current password</span>
          <input
            autoComplete="current-password"
            autoFocus
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
          <button className="button-danger" disabled={submitting} type="submit">
            {submitting ? "Revoking…" : "Revoke sessions"}
          </button>
        </footer>
      </form>
    </dialog>
  );
}

function sessionRevocationMessage(reason: unknown): string {
  if (reason instanceof OperatorPageNotFoundError) {
    return "Operator access is no longer available.";
  }
  if (!(reason instanceof OperatorMutationError)) {
    return "Login Sessions could not be revoked. Try again.";
  }
  if (reason.code === "invalid-password") return "Current password is incorrect.";
  if (reason.code === "invalid-proof") {
    return "Confirmation expired or was already used. Submit again.";
  }
  if (reason.code === "protected-target") {
    return "The current Operator's Login Sessions cannot be revoked here.";
  }
  if (reason.code === "invalid-target") {
    return "This Researcher is no longer available. Refresh the Console.";
  }
  if (reason.code === "rate-limited") {
    return "Too many confirmation attempts. Wait one minute and try again.";
  }
  if (reason.code === "request-invalid") {
    return "The Session revocation request is invalid. Refresh the Console.";
  }
  return "Session service is unavailable. Try again.";
}
