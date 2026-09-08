import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

import { useAuth } from "./AuthProvider";
import { safeReturnTo, type BrowserLocation, type InitialAuthSecret } from "./routing";

type Navigate = (path: string, options?: Readonly<{ replace?: boolean }>) => void;

function LoginPage() {
  const { signIn, sendCode } = useAuth();
  const [email, setEmail] = useState("");
  const [otp, setOtp] = useState("");
  const [sent, setSent] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [retryAt, setRetryAt] = useState(0);
  const [now, setNow] = useState(Date.now());
  const [error, setError] = useState<string | null>(null);
  const otpRef = useRef<HTMLInputElement>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const cooldown = Math.max(0, Math.ceil((retryAt - now) / 1000));

  useEffect(() => {
    if (!retryAt) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [retryAt]);

  useEffect(() => {
    if (sent) otpRef.current?.focus();
  }, [sent]);

  function editEmail(): void {
    setSent(false);
    setOtp("");
    setError(null);
    setRetryAt(0);
    window.requestAnimationFrame(() => emailRef.current?.focus());
  }

  async function requestCode(): Promise<void> {
    if (submitting || cooldown > 0) return;
    setSubmitting(true);
    setError(null);
    const result = await sendCode(email);
    setSubmitting(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    setEmail(email.trim().toLowerCase());
    setOtp("");
    setSent(true);
    setNow(Date.now());
    setRetryAt(Date.now() + 60_000);
  }

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (submitting) return;
    if (!sent) {
      await requestCode();
      return;
    }
    setSubmitting(true);
    setError(null);
    const result = await signIn(email, otp);
    setSubmitting(false);
    if (!result.ok) setError(result.message);
  }

  return (
    <div className="login-page">
      <a className="login-brand" href="/">
        <img src="/quanttrace-logo.png" alt="" width={28} height={28} />
        <span>QuantTrace</span>
      </a>
      <main className="login-main">
      <section className="login-content" aria-labelledby="login-title">
      <header className="login-heading">
        <img src="/quanttrace-logo.png" alt="" width={48} height={48} />
        <h1 id="login-title">{sent ? "Check your email" : "Welcome to QuantTrace"}</h1>
        <p>{sent ? "Enter the six-digit code from your email." : "Sign in or create an account with your email."}</p>
      </header>
      <form className="auth-form" onSubmit={(event) => void submit(event)}>
        {!sent ? (
          <>
            <label htmlFor="login-email">Email</label>
            <input
              autoComplete="email"
              disabled={submitting}
              id="login-email"
              placeholder="you@example.com"
              ref={emailRef}
              onChange={(event) => setEmail(event.target.value)}
              required
              type="email"
              value={email}
            />
          </>
        ) : (
          <>
            <span className="login-email-label">Email</span>
            <div className="login-recipient">
              <span>{email}</span>
              <button className="auth-text-action" type="button" disabled={submitting} onClick={editEmail}>Edit</button>
            </div>
            <label htmlFor="login-code">Verification code</label>
            <div className="login-code-row">
            <input
              autoComplete="one-time-code"
              aria-describedby="login-code-hint"
              aria-invalid={error !== null}
              className="auth-code-input"
              disabled={submitting}
              id="login-code"
              inputMode="numeric"
              maxLength={6}
              minLength={6}
              onChange={(event) => { setOtp(event.target.value.replace(/\D/g, "")); setError(null); }}
              pattern="[0-9]{6}"
              placeholder="Enter 6-digit code"
              ref={otpRef}
              required
              value={otp}
            />
            <button
              className="auth-text-action login-resend"
              aria-label={cooldown > 0 ? `Resend code in ${cooldown}s` : "Resend code"}
              disabled={submitting || cooldown > 0}
              onClick={() => void requestCode()}
              type="button"
            >{cooldown > 0 ? `${cooldown}s` : "Resend"}</button>
            </div>
            <p className="auth-code-hint" id="login-code-hint">Valid for 5 minutes.</p>
          </>
        )}
        {error !== null ? <p className="auth-error" role="alert">{error}</p> : null}
        <button
          className="button-primary auth-submit"
          disabled={submitting || (!sent && cooldown > 0) || (sent && otp.length !== 6)}
          type="submit"
        >
          {submitting
            ? sent ? "Verifying…" : "Sending…"
            : sent ? "Verify and continue" : "Continue with email"}
        </button>
      </form>
      {sent ? (
          <button
            className="auth-text-action login-back"
            disabled={submitting}
            onClick={editEmail}
            type="button"
          >
            Back
          </button>
      ) : (
        <p className="auth-field-hint">
          No password needed. New accounts are created after verification.
        </p>
      )}
      </section>
      </main>
      <footer className="login-footer">QuantTrace · Quantitative research workspace</footer>
    </div>
  );
}

function AcceptInvitationPage({ secret, clearSecret }: {
  secret: InitialAuthSecret | null;
  clearSecret: () => void;
}) {
  const { acceptInvitation, inspectInvitation } = useAuth();
  const token = secret?.kind === "invitation" ? secret.token : null;
  const [email, setEmail] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [loading, setLoading] = useState(token !== null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(token === null
    ? "This invitation link is invalid."
    : null);
  const inspected = useRef(false);

  useEffect(() => {
    if (token === null || inspected.current) return;
    inspected.current = true;
    let active = true;
    void inspectInvitation(token)
      .then((result) => {
        if (!active) return;
        if (result === null) setError("This invitation is invalid or has expired.");
        else setEmail(result.email);
      })
      .catch(() => {
        if (active) setError("Authentication is temporarily unavailable.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [inspectInvitation, token]);

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (token === null || email === null || submitting) return;
    if (password !== confirmation) {
      setError("Passwords do not match.");
      return;
    }
    setSubmitting(true);
    setError(null);
    const result = await acceptInvitation(token, password);
    setSubmitting(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    clearSecret();
  }

  return (
    <AuthSurface eyebrow="Invitation" title="Create your ThesisTrace access">
      {loading ? <p role="status">Checking invitation…</p> : null}
      {!loading && email !== null ? (
        <form className="auth-form" onSubmit={(event) => void submit(event)}>
          <label htmlFor="invitation-email">Email</label>
          <input autoComplete="email" id="invitation-email" readOnly type="email" value={email} />
          <label htmlFor="invitation-password">Password</label>
          <input
            autoComplete="new-password"
            id="invitation-password"
            maxLength={128}
            minLength={12}
            onChange={(event) => setPassword(event.target.value)}
            required
            type="password"
            value={password}
          />
          <span className="auth-field-hint">Use 12–128 characters.</span>
          <label htmlFor="invitation-password-confirmation">Confirm password</label>
          <input
            autoComplete="new-password"
            id="invitation-password-confirmation"
            maxLength={128}
            minLength={12}
            onChange={(event) => setConfirmation(event.target.value)}
            required
            type="password"
            value={confirmation}
          />
          {error !== null ? <p className="auth-error" role="alert">{error}</p> : null}
          <button className="button-primary auth-submit" disabled={submitting} type="submit">
            {submitting ? "Creating access…" : "Accept invitation"}
          </button>
        </form>
      ) : null}
      {!loading && email === null && error !== null ? <p className="auth-error" role="alert">{error}</p> : null}
    </AuthSurface>
  );
}

export function AuthRoute({
  clearSecret,
  location,
  navigate,
  secret,
}: {
  clearSecret: () => void;
  location: BrowserLocation;
  navigate: Navigate;
  secret: InitialAuthSecret | null;
}) {
  switch (location.pathname) {
    case "/login":
      return <LoginPage />;
    case "/accept-invitation":
      return (
        <AcceptInvitationPage
          clearSecret={clearSecret}
          key={secret?.kind === "invitation" ? secret.token : "missing-invitation"}
          secret={secret}
        />
      );
    default:
      return null;
  }
}

export function returnToFromLocation(location: BrowserLocation): string | null {
  return safeReturnTo(
    new URLSearchParams(location.search).get("returnTo"),
    window.location.origin,
  );
}

export function AuthSurface({ eyebrow, title, children }: {
  eyebrow: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <main className="auth-page">
      <section aria-labelledby="auth-title" className="auth-panel">
        <a className="auth-brand" href="/login">
          <img src="/quanttrace-logo.png" alt="" width={30} height={30} />
          <span>QuantTrace</span>
        </a>
        <header>
          <span className="auth-eyebrow">{eyebrow}</span>
          <h1 id="auth-title">{title}</h1>
        </header>
        {children}
      </section>
    </main>
  );
}
