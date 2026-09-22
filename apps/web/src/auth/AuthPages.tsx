import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

import { useAuth } from "./AuthProvider";
import { Brand, BrandMark } from "../brand/Brand";
import { safeReturnTo, type BrowserLocation, type InitialAuthSecret } from "./routing";
import { interfaceLocale, publicLanguageCode, useTranslation } from "../i18n";
import type { AuthErrorCode } from "./errors";

type Navigate = (path: string, options?: Readonly<{ replace?: boolean }>) => void;

function LoginPage() {
  const { t } = useTranslation("auth");
  const { signIn, sendCode } = useAuth();
  const [email, setEmail] = useState("");
  const [otp, setOtp] = useState("");
  const [sent, setSent] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [retryAt, setRetryAt] = useState(0);
  const [now, setNow] = useState(Date.now());
  const [error, setError] = useState<AuthErrorCode | null>(null);
  const otpRef = useRef<HTMLInputElement>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const cooldown = Math.max(0, Math.ceil((retryAt - now) / 1000));
  useEffect(() => {
    document.title = `${t(sent ? "checkEmail" : "welcome")} · Quantgrove`;
    document.querySelector('meta[name="description"]')?.setAttribute("content", t("introduction"));
  }, [sent, t]);

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
      setError(result.code);
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
    if (!result.ok) setError(result.code);
  }

  return (
    <div className="login-page">
      <a className="login-brand" href={`/?lang=${publicLanguageCode(interfaceLocale())}`}>
        <Brand size={28} />
      </a>
      <main className="login-main">
      <section className="login-content" aria-labelledby="login-title">
      <header className="login-heading">
        <BrandMark size={48} />
        <h1 id="login-title">{t(sent ? "checkEmail" : "welcome")}</h1>
        <p>{t(sent ? "enterCode" : "introduction")}</p>
      </header>
      <form className="auth-form" onSubmit={(event) => void submit(event)}>
        {!sent ? (
          <>
            <label htmlFor="login-email">{t("email")}</label>
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
            <span className="login-email-label">{t("email")}</span>
            <div className="login-recipient">
              <span>{email}</span>
              <button className="auth-text-action" type="button" disabled={submitting} onClick={editEmail}>{t("edit")}</button>
            </div>
            <label htmlFor="login-code">{t("verificationCode")}</label>
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
              placeholder={t("codePlaceholder")}
              ref={otpRef}
              required
              value={otp}
            />
            <button
              className="auth-text-action login-resend"
              aria-label={cooldown > 0 ? t("resendIn", { seconds: cooldown }) : t("resendCode")}
              disabled={submitting || cooldown > 0}
              onClick={() => void requestCode()}
              type="button"
            >{cooldown > 0 ? t("seconds", { seconds: cooldown }) : t("resend")}</button>
            </div>
            <p className="auth-code-hint" id="login-code-hint">{t("validFor")}</p>
          </>
        )}
        {error !== null ? <p className="auth-error" role="alert">{t(`errors.${error}`)}</p> : null}
        <button
          className="button-primary auth-submit"
          disabled={submitting || (!sent && cooldown > 0) || (sent && otp.length !== 6)}
          type="submit"
        >
          {t(submitting ? sent ? "verifying" : "sending" : sent ? "verifyContinue" : "continueEmail")}
        </button>
      </form>
      {sent ? (
          <button
            className="auth-text-action login-back"
            disabled={submitting}
            onClick={editEmail}
            type="button"
          >
            {t("back")}
          </button>
      ) : (
        <p className="auth-field-hint">
          {t("noPassword")}
        </p>
      )}
      </section>
      </main>
      <footer className="login-footer">{t("footer")}</footer>
    </div>
  );
}

function AcceptInvitationPage({ secret, clearSecret }: {
  secret: InitialAuthSecret | null;
  clearSecret: () => void;
}) {
  const { t } = useTranslation("auth");
  const { acceptInvitation, inspectInvitation } = useAuth();
  const token = secret?.kind === "invitation" ? secret.token : null;
  const [email, setEmail] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [loading, setLoading] = useState(token !== null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<AuthErrorCode | null>(token === null
    ? "invalidInvitation"
    : null);
  const inspected = useRef(false);

  useEffect(() => {
    if (token === null || inspected.current) return;
    inspected.current = true;
    let active = true;
    void inspectInvitation(token)
      .then((result) => {
        if (!active) return;
        if (!result.ok) setError(result.code);
        else setEmail(result.email);
      })
      .catch(() => {
        if (active) setError("unavailable");
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
      setError("passwordMismatch");
      return;
    }
    setSubmitting(true);
    setError(null);
    const result = await acceptInvitation(token, password);
    setSubmitting(false);
    if (!result.ok) {
      setError(result.code);
      return;
    }
    clearSecret();
  }

  return (
    <AuthSurface eyebrow={t("invitation")} title={t("createAccess")}>
      {loading ? <p role="status">{t("checkingInvitation")}</p> : null}
      {!loading && email !== null ? (
        <form className="auth-form" onSubmit={(event) => void submit(event)}>
          <label htmlFor="invitation-email">{t("email")}</label>
          <input autoComplete="email" id="invitation-email" readOnly type="email" value={email} />
          <label htmlFor="invitation-password">{t("password")}</label>
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
          <span className="auth-field-hint">{t("passwordHint")}</span>
          <label htmlFor="invitation-password-confirmation">{t("confirmPassword")}</label>
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
          {error !== null ? <p className="auth-error" role="alert">{t(`errors.${error}`)}</p> : null}
          <button className="button-primary auth-submit" disabled={submitting} type="submit">
            {t(submitting ? "creatingAccess" : "acceptInvitation")}
          </button>
        </form>
      ) : null}
      {!loading && email === null && error !== null ? <p className="auth-error" role="alert">{t(`errors.${error}`)}</p> : null}
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
  const { t } = useTranslation("auth");
  useEffect(() => {
    document.title = `${title} · Quantgrove`;
    document.querySelector('meta[name="description"]')?.setAttribute("content", t("footer"));
  }, [title, t]);
  return (
    <main className="auth-page">
      <section aria-labelledby="auth-title" className="auth-panel">
        <a className="auth-brand" href={`/login?lang=${publicLanguageCode(interfaceLocale())}`}>
          <Brand />
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
