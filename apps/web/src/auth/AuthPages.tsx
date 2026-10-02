import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

import { useAuthRetry } from "./useAuthRetry";
import { useAuth } from "./AuthProvider";
import { Brand, BrandMark } from "../brand/Brand";
import { safeReturnTo, type BrowserLocation, type InitialAuthSecret } from "./routing";
import { interfaceLocale, publicLanguageCode, useTranslation } from "../i18n";
import type { AuthErrorCode } from "./errors";
import { Alert, AlertDescription } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Field, FieldDescription, FieldGroup, FieldLabel, FieldTitle } from "../components/ui/field";
import { Input } from "../components/ui/input";
import { Spinner } from "../components/ui/spinner";

type Navigate = (path: string, options?: Readonly<{ replace?: boolean }>) => void;

function LoginPage() {
  const { t } = useTranslation("auth");
  const { signIn, sendCode } = useAuth();
  const [email, setEmail] = useState("");
  const [otp, setOtp] = useState("");
  const [sent, setSent] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [retryAt, setRetryAt] = useState(0);
  const [errorRetryAt, setErrorRetryAt] = useState(0);
  const serverSendRetryAt = useRef(0);
  const [verificationRetryAt, setVerificationRetryAt] = useState(0);
  const [error, setError] = useState<AuthErrorCode | null>(null);
  const otpRef = useRef<HTMLInputElement>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const cooldown = useAuthRetry(retryAt);
  const verificationCooldown = useAuthRetry(verificationRetryAt);
  const errorCooldown = useAuthRetry(errorRetryAt);
  useEffect(() => {
    document.title = `${t(sent ? "checkEmail" : "welcome")} · Quantgrove`;
    document.querySelector('meta[name="description"]')?.setAttribute("content", t("introduction"));
  }, [sent, t]);

  useEffect(() => {
    if (sent) otpRef.current?.focus();
  }, [sent]);

  function editEmail(): void {
    setSent(false);
    setOtp("");
    setError(null);
    setRetryAt(serverSendRetryAt.current);
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
      if (result.retryAfterSeconds !== undefined) {
        const deadline = Date.now() + result.retryAfterSeconds * 1_000;
        serverSendRetryAt.current = deadline;
        setRetryAt(deadline);
        setErrorRetryAt(deadline);
      }
      return;
    }
    setEmail(email.trim().toLowerCase());
    setOtp("");
    setSent(true);
    setRetryAt(Date.now() + 60_000);
  }

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (submitting || (sent && verificationCooldown > 0)) return;
    if (!sent) {
      await requestCode();
      return;
    }
    setSubmitting(true);
    setError(null);
    const result = await signIn(email, otp);
    setSubmitting(false);
    if (!result.ok) {
      setError(result.code);
      if (result.retryAfterSeconds !== undefined) {
        const deadline = Date.now() + result.retryAfterSeconds * 1_000;
        setVerificationRetryAt(deadline);
        setErrorRetryAt(deadline);
      }
    }
  }

  return (
    <div className="login-page">
      <a className="login-brand" href={`/?lang=${publicLanguageCode(interfaceLocale())}`}>
        <Brand size={28} inverse />
      </a>
      <main className="login-main">
      <section className="login-content" aria-labelledby="login-title">
      <header className="login-heading">
        <BrandMark size={48} inverse />
        <h1 id="login-title">{t(sent ? "checkEmail" : "welcome")}</h1>
        <p>{t(sent ? "enterCode" : "introduction")}</p>
      </header>
      <form onSubmit={(event) => void submit(event)}>
        <FieldGroup className="gap-4">
          {!sent ? (
            <Field data-disabled={submitting}>
              <FieldLabel htmlFor="login-email">{t("email")}</FieldLabel>
              <Input
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
            </Field>
          ) : (
            <>
              <Field>
                <FieldTitle>{t("email")}</FieldTitle>
                <div className="flex min-w-0 items-center justify-between gap-2 rounded-md border border-border bg-card p-2 pl-3">
                  <span className="min-w-0 break-all text-sm">{email}</span>
                  <Button variant="link" type="button" disabled={submitting} onClick={editEmail}>{t("edit")}</Button>
                </div>
              </Field>
              <Field data-invalid={error !== null} data-disabled={submitting}>
                <FieldLabel htmlFor="login-code">{t("verificationCode")}</FieldLabel>
                <div className="flex min-w-0 items-center gap-2">
                  <Input
                    autoComplete="one-time-code"
                    aria-describedby="login-code-hint"
                    aria-invalid={error !== null}
                    className="min-w-0 flex-1"
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
                  <Button
                    variant="outline"
                    className="shrink-0"
                    aria-label={cooldown > 0 ? t("resendIn", { seconds: cooldown }) : t("resendCode")}
                    disabled={submitting || cooldown > 0}
                    onClick={() => void requestCode()}
                    type="button"
                  >{cooldown > 0 ? t("seconds", { seconds: cooldown }) : t("resend")}</Button>
                </div>
                <FieldDescription id="login-code-hint">{t("validFor")}</FieldDescription>
              </Field>
            </>
          )}
          {error !== null ? <Alert variant="destructive"><AlertDescription>{error === "tooManyRequests" && errorCooldown > 0 ? t("rateLimited", {seconds: errorCooldown}) : t(`errors.${error}`)}</AlertDescription></Alert> : null}
          <Button
            className="w-full"
            disabled={submitting || (!sent && cooldown > 0) || (sent && (otp.length !== 6 || verificationCooldown > 0))}
            size="lg"
            type="submit"
          >
            {submitting ? <Spinner data-icon="inline-start" aria-hidden="true" /> : null}
            {t(submitting ? sent ? "verifying" : "sending" : sent ? "verifyContinue" : "continueEmail")}
          </Button>
        </FieldGroup>
      </form>
      {sent ? (
          <Button
            className="mx-auto mt-3 flex"
            variant="link"
            disabled={submitting}
            onClick={editEmail}
            type="button"
          >
            {t("back")}
          </Button>
      ) : (
        <p className="mt-4 text-center text-xs text-muted-foreground">
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
  const [retryAt, setRetryAt] = useState(0);
  const cooldown = useAuthRetry(retryAt);

  useEffect(() => {
    if (token === null || inspected.current) return;
    inspected.current = true;
    let active = true;
    void inspectInvitation(token)
      .then((result) => {
        if (!active) return;
        if (!result.ok) {
          setError(result.code);
          if (result.retryAfterSeconds !== undefined) setRetryAt(Date.now() + result.retryAfterSeconds * 1_000);
        }
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

  async function retryInspection(): Promise<void> {
    if (token === null || loading || cooldown > 0) return;
    setLoading(true);
    setError(null);
    try {
      const result = await inspectInvitation(token);
      if (result.ok) setEmail(result.email);
      else {
        setError(result.code);
        if (result.retryAfterSeconds !== undefined) setRetryAt(Date.now() + result.retryAfterSeconds * 1_000);
      }
    } finally { setLoading(false); }
  }

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (token === null || email === null || submitting || cooldown > 0) return;
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
      if (result.retryAfterSeconds !== undefined) setRetryAt(Date.now() + result.retryAfterSeconds * 1_000);
      return;
    }
    clearSecret();
  }

  return (
    <AuthSurface eyebrow={t("invitation")} title={t("createAccess")}>
      {loading ? <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status"><Spinner aria-hidden="true" />{t("checkingInvitation")}</p> : null}
      {!loading && email !== null ? (
        <form onSubmit={(event) => void submit(event)}>
          <FieldGroup className="gap-4">
            <Field>
              <FieldLabel htmlFor="invitation-email">{t("email")}</FieldLabel>
              <Input autoComplete="email" id="invitation-email" readOnly type="email" value={email} />
            </Field>
            <Field data-disabled={submitting}>
              <FieldLabel htmlFor="invitation-password">{t("password")}</FieldLabel>
              <Input
                autoComplete="new-password"
                disabled={submitting}
                id="invitation-password"
                maxLength={128}
                minLength={12}
                onChange={(event) => setPassword(event.target.value)}
                required
                type="password"
                value={password}
              />
              <FieldDescription>{t("passwordHint")}</FieldDescription>
            </Field>
            <Field data-disabled={submitting} data-invalid={error === "passwordMismatch"}>
              <FieldLabel htmlFor="invitation-password-confirmation">{t("confirmPassword")}</FieldLabel>
              <Input
                aria-invalid={error === "passwordMismatch"}
                autoComplete="new-password"
                disabled={submitting}
                id="invitation-password-confirmation"
                maxLength={128}
                minLength={12}
                onChange={(event) => setConfirmation(event.target.value)}
                required
                type="password"
                value={confirmation}
              />
            </Field>
            {error !== null ? <Alert variant="destructive"><AlertDescription>{error === "tooManyRequests" && cooldown > 0 ? t("rateLimited", {seconds: cooldown}) : t(`errors.${error}`)}</AlertDescription></Alert> : null}
            <Button className="w-full" disabled={submitting || cooldown > 0} size="lg" type="submit">
              {submitting ? <Spinner data-icon="inline-start" aria-hidden="true" /> : null}
              {t(submitting ? "creatingAccess" : "acceptInvitation")}
            </Button>
          </FieldGroup>
        </form>
      ) : null}
      {!loading && email === null && error !== null ? <Alert variant="destructive"><AlertDescription>{error === "tooManyRequests" && cooldown > 0 ? t("rateLimited", {seconds: cooldown}) : t(`errors.${error}`)}</AlertDescription></Alert> : null}
      {!loading && email === null && error === "tooManyRequests" ? <Button className="mt-4 w-full" disabled={cooldown > 0} onClick={() => void retryInspection()} type="button">{t("retry")}</Button> : null}
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

export function AuthSurface({ eyebrow, title, children, as: Root = "main" }: {
  as?: "main" | "section";
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
    <Root className="auth-page">
      <section aria-labelledby="auth-title" className="auth-panel">
        <a className="auth-brand" href={`/login?lang=${publicLanguageCode(interfaceLocale())}`}>
          <Brand inverse />
        </a>
        <header>
          <span className="auth-eyebrow">{eyebrow}</span>
          <h1 id="auth-title">{title}</h1>
        </header>
        {children}
      </section>
    </Root>
  );
}
