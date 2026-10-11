import { useEffect, useState, type RefObject } from "react";
import { Turnstile, type TurnstileInstance } from "@marsidev/react-turnstile";
import { z } from "zod";
import { useTranslation, interfaceLocale } from "../i18n";
import { Button } from "../components/ui/button";
import { Alert, AlertDescription } from "../components/ui/alert";
import { Spinner } from "../components/ui/spinner";

const configSchema = z.object({siteKey: z.string().min(20).max(128), action: z.literal("sign-in-code")});
export function SignInChallenge({widgetRef, onToken}: {
  widgetRef: RefObject<TurnstileInstance | null>;
  onToken: (token: string | null) => void;
}) {
  const {t} = useTranslation("auth");
  const [config, setConfig] = useState<z.infer<typeof configSchema> | null>(null);
  const [scriptFailed, setScriptFailed] = useState(false);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setFailed(false);
    setConfig(null);
    void fetch("/api/auth/email-otp/challenge", {credentials: "same-origin", signal: AbortSignal.any([controller.signal, AbortSignal.timeout(10000)])})
      .then(async response => {
        if (!response.ok) throw new Error("Challenge unavailable");
        const value = configSchema.parse(await response.json());
        if (!controller.signal.aborted) setConfig(value);
      })
      .catch(() => {if (!controller.signal.aborted) setFailed(true);});
    return () => controller.abort();
  }, [attempt]);
  const fail = () => {onToken(null); setFailed(true);};
  return <div className="flex flex-col items-center gap-2">
    {config ? <Turnstile ref={widgetRef} siteKey={config.siteKey}
      options={{action: config.action, theme: "dark", language: interfaceLocale() === "zh-CN" ? "zh-cn" : "en", refreshExpired: "auto"}}
      onSuccess={token => {setFailed(false); onToken(token);}}
      onExpire={() => onToken(null)} onError={fail} onTimeout={fail}
      scriptOptions={{onError: () => {setScriptFailed(true); fail();}}} /> : !failed ? <p className="flex items-center gap-2 text-sm text-muted-foreground"><Spinner aria-hidden="true" />{t("checkingHuman")}</p> : null}
    {failed ? <><Alert variant="destructive"><AlertDescription>{t("errors.challengeFailed")}</AlertDescription></Alert>
      <Button type="button" variant="outline" onClick={() => {if (scriptFailed) {window.location.reload(); return;} onToken(null); setFailed(false); setAttempt(value => value + 1);}}>{t(scriptFailed ? "reload" : "retry")}</Button></> : null}
  </div>;
}
