import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

import { useAuth } from "./AuthProvider";
import { safeReturnTo, type BrowserLocation, type InitialAuthSecret } from "./routing";

type Navigate = (path: string, options?: Readonly<{ replace?: boolean }>) => void;

function LoginPage({ location, navigate }: {
  location: BrowserLocation;
  navigate: Navigate;
}) {
  const { signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const resetComplete = new URLSearchParams(location.search).get("reset") === "complete";

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    const result = await signIn(email, password);
    setSubmitting(false);
    if (!result.ok) setError(result.message);
  }

  return (
    <AuthSurface eyebrow="Research workspace" title="Log in to ThesisTrace">
      {resetComplete ? <p className="auth-success" role="status">Password reset. Log in with your new password.</p> : null}
      <form className="auth-form" onSubmit={(event) => void submit(event)}>
        <label htmlFor="login-email">Email</label>
        <input
          autoComplete="email"
          id="login-email"
          onChange={(event) => setEmail(event.target.value)}
          required
          type="email"
          value={email}
        />
        <label htmlFor="login-password">Password</label>
        <input
          autoComplete="current-password"
          id="login-password"
          maxLength={128}
          minLength={12}
          onChange={(event) => setPassword(event.target.value)}
          required
          type="password"
          value={password}
        />
        {error !== null ? <p className="auth-error" role="alert">{error}</p> : null}
        <button className="button-primary auth-submit" disabled={submitting} type="submit">
          {submitting ? "Logging in…" : "Log in"}
        </button>
      </form>
      <button className="auth-text-action" onClick={() => navigate("/forgot-password")} type="button">
        Forgot password?
      </button>
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

function ForgotPasswordPage({ navigate }: { navigate: Navigate }) {
  const { requestPasswordReset } = useAuth();
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    const result = await requestPasswordReset(email);
    setSubmitting(false);
    if (result.ok) setSent(true);
    else setError(result.message);
  }

  return (
    <AuthSurface eyebrow="Account recovery" title="Reset your password">
      {sent ? (
        <p className="auth-success" role="status">
          If the account exists, a reset link has been sent.
        </p>
      ) : (
        <form className="auth-form" onSubmit={(event) => void submit(event)}>
          <label htmlFor="recovery-email">Email</label>
          <input
            autoComplete="email"
            id="recovery-email"
            onChange={(event) => setEmail(event.target.value)}
            required
            type="email"
            value={email}
          />
          {error !== null ? <p className="auth-error" role="alert">{error}</p> : null}
          <button className="button-primary auth-submit" disabled={submitting} type="submit">
            {submitting ? "Sending…" : "Send reset link"}
          </button>
        </form>
      )}
      <button className="auth-text-action" onClick={() => navigate("/login")} type="button">
        Return to login
      </button>
    </AuthSurface>
  );
}

function ResetPasswordPage({ secret, clearSecret, navigate }: {
  secret: InitialAuthSecret | null;
  clearSecret: () => void;
  navigate: Navigate;
}) {
  const { resetPassword } = useAuth();
  const token = secret?.kind === "password-reset" ? secret.token : null;
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(token === null
    ? "This reset link is invalid."
    : null);

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (token === null || submitting) return;
    if (password !== confirmation) {
      setError("Passwords do not match.");
      return;
    }
    setSubmitting(true);
    setError(null);
    const result = await resetPassword(token, password);
    setSubmitting(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    clearSecret();
    navigate("/login?reset=complete", { replace: true });
  }

  return (
    <AuthSurface eyebrow="Account recovery" title="Choose a new password">
      {token !== null ? (
        <form className="auth-form" onSubmit={(event) => void submit(event)}>
          <label htmlFor="reset-password">New password</label>
          <input
            autoComplete="new-password"
            id="reset-password"
            maxLength={128}
            minLength={12}
            onChange={(event) => setPassword(event.target.value)}
            required
            type="password"
            value={password}
          />
          <span className="auth-field-hint">Use 12–128 characters.</span>
          <label htmlFor="reset-password-confirmation">Confirm password</label>
          <input
            autoComplete="new-password"
            id="reset-password-confirmation"
            maxLength={128}
            minLength={12}
            onChange={(event) => setConfirmation(event.target.value)}
            required
            type="password"
            value={confirmation}
          />
          {error !== null ? <p className="auth-error" role="alert">{error}</p> : null}
          <button className="button-primary auth-submit" disabled={submitting} type="submit">
            {submitting ? "Resetting…" : "Reset password"}
          </button>
        </form>
      ) : <p className="auth-error" role="alert">{error}</p>}
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
      return <LoginPage location={location} navigate={navigate} />;
    case "/accept-invitation":
      return (
        <AcceptInvitationPage
          clearSecret={clearSecret}
          key={secret?.kind === "invitation" ? secret.token : "missing-invitation"}
          secret={secret}
        />
      );
    case "/forgot-password":
      return <ForgotPasswordPage navigate={navigate} />;
    case "/reset-password":
      return (
        <ResetPasswordPage
          clearSecret={clearSecret}
          key={secret?.kind === "password-reset" ? secret.token : "missing-password-reset"}
          navigate={navigate}
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
          <span className="brand-mark" aria-hidden="true">T</span>
          <span>ThesisTrace</span>
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
