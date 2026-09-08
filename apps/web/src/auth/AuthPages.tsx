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
  const cooldown = Math.max(0, Math.ceil((retryAt - now) / 1000));

  useEffect(() => {
    if (!retryAt) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [retryAt]);

  useEffect(() => {
    if (sent) otpRef.current?.focus();
  }, [sent]);

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
    <AuthSurface
      eyebrow="Quantitative research workspace"
      title={sent ? "Check your email" : "Get started with QuantTrace"}
    >
      <p>
        {sent
          ? `Enter the six-digit code sent to ${email}. It expires in 5 minutes.`
          : "Sign in or create an account with your email. No password needed."}
      </p>
      <form className="auth-form" onSubmit={(event) => void submit(event)}>
        {!sent ? (
          <>
            <label htmlFor="login-email">Email</label>
            <input
              autoComplete="email"
              disabled={submitting}
              id="login-email"
              onChange={(event) => setEmail(event.target.value)}
              required
              type="email"
              value={email}
            />
          </>
        ) : (
          <>
            <label htmlFor="login-code">Verification code</label>
            <input
              autoComplete="one-time-code"
              disabled={submitting}
              id="login-code"
              inputMode="numeric"
              maxLength={6}
              minLength={6}
              onChange={(event) => setOtp(event.target.value)}
              pattern="[0-9]{6}"
              ref={otpRef}
              required
              value={otp}
            />
          </>
        )}
        {error !== null ? <p className="auth-error" role="alert">{error}</p> : null}
        <button
          className="button-primary auth-submit"
          disabled={submitting || (!sent && cooldown > 0)}
          type="submit"
        >
          {submitting
            ? sent ? "Verifying…" : "Sending…"
            : sent ? "Verify and continue" : "Continue with email"}
        </button>
      </form>
      {sent ? (
        <div className="auth-secondary-actions">
          <button
            className="auth-text-action"
            disabled={submitting || cooldown > 0}
            onClick={() => void requestCode()}
            type="button"
          >
            {cooldown > 0 ? `Resend code in ${cooldown}s` : "Resend code"}
          </button>
          <button
            className="auth-text-action"
            disabled={submitting}
            onClick={() => {
              setSent(false);
              setOtp("");
              setError(null);
              setRetryAt(0);
            }}
            type="button"
          >
            Use a different email
          </button>
        </div>
      ) : (
        <p className="auth-field-hint">
          One email, one account. Your account is created after verification.
        </p>
      )}
    </AuthSurface>
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
