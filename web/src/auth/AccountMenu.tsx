import { SignOut, UserCircle } from "@phosphor-icons/react";
import { useState, type FormEvent } from "react";

import { useAuth } from "./AuthProvider";
import type { PublicSession } from "./session";

type AccountActionResult = Readonly<{ ok: true }> | Readonly<{ ok: false; message: string }>;

type AccountMenuContentProps = Readonly<{
  changePassword: (currentPassword: string, newPassword: string) => Promise<AccountActionResult>;
  session: PublicSession;
  signOut: () => Promise<AccountActionResult>;
}>;

export function AccountMenu() {
  const { changePassword, signOut, state } = useAuth();
  if (state.session === null) return null;
  return (
    <AccountMenuContent
      changePassword={changePassword}
      key={state.session.researcherId}
      session={state.session}
      signOut={signOut}
    />
  );
}

export function AccountMenuContent({
  changePassword,
  session,
  signOut,
}: AccountMenuContentProps) {
  const [changingPassword, setChangingPassword] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  async function submitPassword(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (submitting) return;
    if (newPassword !== confirmation) {
      setMessage("Passwords do not match.");
      return;
    }
    setSubmitting(true);
    setMessage(null);
    const result = await changePassword(currentPassword, newPassword);
    setSubmitting(false);
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    setCurrentPassword("");
    setNewPassword("");
    setConfirmation("");
    setMessage("Password changed. Other sessions were logged out.");
  }

  async function submitSignOut(): Promise<void> {
    if (signingOut) return;
    setSigningOut(true);
    setMessage(null);
    const result = await signOut();
    if (!result.ok) {
      setSigningOut(false);
      setMessage(result.message);
    }
  }

  return (
    <details className="account-menu">
      <summary aria-label="Account menu">
        <UserCircle aria-hidden="true" size={18} />
        <span>{session.displayLabel}</span>
      </summary>
      <div className="account-menu-panel">
        <div className="account-identity">
          <strong>{session.displayLabel}</strong>
          <span>{session.email}</span>
        </div>
        <button
          className="account-action"
          onClick={() => {
            setChangingPassword((visible) => !visible);
            setMessage(null);
          }}
          type="button"
        >
          Change password
        </button>
        {changingPassword ? (
          <form className="account-password-form" onSubmit={(event) => void submitPassword(event)}>
            <label htmlFor="account-current-password">Current password</label>
            <input
              autoComplete="current-password"
              id="account-current-password"
              maxLength={128}
              minLength={12}
              onChange={(event) => setCurrentPassword(event.target.value)}
              required
              type="password"
              value={currentPassword}
            />
            <label htmlFor="account-new-password">New password</label>
            <input
              autoComplete="new-password"
              id="account-new-password"
              maxLength={128}
              minLength={12}
              onChange={(event) => setNewPassword(event.target.value)}
              required
              type="password"
              value={newPassword}
            />
            <label htmlFor="account-confirm-password">Confirm password</label>
            <input
              autoComplete="new-password"
              id="account-confirm-password"
              maxLength={128}
              minLength={12}
              onChange={(event) => setConfirmation(event.target.value)}
              required
              type="password"
              value={confirmation}
            />
            {message !== null ? <p role="status">{message}</p> : null}
            <button className="button-primary" disabled={submitting} type="submit">
              {submitting ? "Changing…" : "Change password"}
            </button>
          </form>
        ) : message !== null ? <p className="account-message" role="status">{message}</p> : null}
        <button
          className="account-action"
          disabled={signingOut}
          onClick={() => void submitSignOut()}
          type="button"
        >
          <SignOut aria-hidden="true" size={16} />
          {signingOut ? "Logging out…" : "Log out"}
        </button>
      </div>
    </details>
  );
}
