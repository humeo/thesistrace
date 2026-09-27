import { useId, useState, type Ref } from "react";
import { useTranslation } from "../i18n";

import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Field, FieldLabel } from "../components/ui/field";

export function OperatorCodeField({value, onChange, disabled, autoFocus = true, inputRef}: Readonly<{
  inputRef?: Ref<HTMLInputElement>; autoFocus?: boolean; value: string; onChange: (value: string) => void; disabled: boolean;
}>) {
  const id = useId();
  const { t } = useTranslation("operator");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [message, setMessage] = useState<"sent" | "failed" | null>(null);
  async function send() {
    if (sending || disabled) return;
    setSending(true); setMessage(null);
    try {
      const response = await fetch("/api/auth/operator/proofs/send-code", {
        method: "POST", credentials: "same-origin",
        headers: {"Content-Type": "application/json"}, body: "{}",
      });
      if (!response.ok) throw new Error();
      onChange(""); setSent(true); setMessage("sent");
    } catch { setMessage("failed"); }
    finally { setSending(false); }
  }
  return <Field>
    <FieldLabel htmlFor={id}>{t("researchers.code.label")}</FieldLabel>
    <Input id={id} ref={inputRef} autoFocus={autoFocus} autoComplete="one-time-code" inputMode="numeric" pattern="[0-9]{6}" minLength={6} maxLength={6} required disabled={disabled || sending} value={value} onChange={event => onChange(event.target.value)} />
    <Button variant="outline" type="button" disabled={disabled || sending} onClick={() => void send()}>{sending ? t("researchers.code.sending") : sent ? t("researchers.code.resend") : t("researchers.code.send")}</Button>
    {message ? <p role="status" className="m-0 text-sm leading-[22px] text-muted-foreground">{t(`researchers.code.${message}`)}</p> : null}
  </Field>;
}
