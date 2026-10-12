import type { TurnstileInstance } from "@marsidev/react-turnstile";
import { lazy, Suspense, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

import { useAuthRetry } from "./useAuthRetry";
import { useAuth } from "./AuthProvider";
import { Brand, BrandMark } from "../brand/Brand";
import { safeReturnTo, type BrowserLocation } from "./routing";
import { interfaceLocale, publicLanguageCode, useTranslation } from "../i18n";
import type { AuthErrorCode } from "./errors";
import { Alert, AlertDescription } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Field, FieldDescription, FieldGroup, FieldLabel, FieldTitle } from "../components/ui/field";
import { Input } from "../components/ui/input";
import { InputOTP, InputOTPSlot } from "../components/ui/input-otp";
import { Spinner } from "../components/ui/spinner";

const SignInChallenge = lazy(() => import("./SignInChallenge").then(module => ({default: module.SignInChallenge})));

function LoginPage() {
  const { t } = useTranslation("auth");
  const { signIn, sendCode } = useAuth();
  const [challengeToken, setChallengeToken] = useState<string | null>(null);
  const challengeRef = useRef<TurnstileInstance>(null);
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
    document.title = `${t(sent ? "checkEmail" : "welcome")} · QAgentis`;
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
    if (submitting || cooldown > 0 || challengeToken === null) return;
    setSubmitting(true);
    setError(null);
    const result = await sendCode(email, challengeToken);
    setChallengeToken(null);
    challengeRef.current?.reset();
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
    serverSendRetryAt.current = Date.now() + 60_000;
    setRetryAt(serverSendRetryAt.current);
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
                  <InputOTP
                    aria-describedby="login-code-hint"
                    className="min-w-0 flex-1"
                    disabled={submitting}
                    id="login-code"
                    length={6}
                    onValueChange={(value) => { setOtp(value); setError(null); }}
                    required
                    value={otp}
                  >
                    {Array.from({ length: 6 }, (_, index) => (
                      <InputOTPSlot
                        key={index}
                        aria-describedby="login-code-hint"
                        aria-invalid={error !== null}
                        aria-label={index === 0 ? undefined : t("codeDigit", { position: index + 1 })}
                        ref={index === 0 ? otpRef : undefined}
                      />
                    ))}
                  </InputOTP>
                  <Button
                    variant="outline"
                    className="shrink-0"
                    aria-label={cooldown > 0 ? t("resendIn", { seconds: cooldown }) : t("resendCode")}
                    disabled={submitting || cooldown > 0 || challengeToken === null}
                    onClick={() => void requestCode()}
                    type="button"
                  >{cooldown > 0 ? t("seconds", { seconds: cooldown }) : t("resend")}</Button>
                </div>
                <FieldDescription id="login-code-hint">{t("validFor")}</FieldDescription>
              </Field>
            </>
          )}
          <Suspense fallback={<p className="text-center text-sm text-muted-foreground">{t("checkingHuman")}</p>}>
            <SignInChallenge widgetRef={challengeRef} onToken={setChallengeToken} />
          </Suspense>
          {error !== null ? <Alert variant="destructive"><AlertDescription>{error === "tooManyRequests" && errorCooldown > 0 ? t("rateLimited", {seconds: errorCooldown}) : t(`errors.${error}`)}</AlertDescription></Alert> : null}
          <Button
            className="w-full"
            disabled={submitting || (!sent && (cooldown > 0 || challengeToken === null)) || (sent && (otp.length !== 6 || verificationCooldown > 0))}
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
    document.title = `${title} · QAgentis`;
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

export function AuthRoute({ location }: { location: BrowserLocation }) {
  return location.pathname === "/login" ? <LoginPage /> : null;
}
