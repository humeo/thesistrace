import { useState } from "react";
import { useTranslation } from "../i18n";

export function OperatorCodeField({value, onChange, disabled, autoFocus = true}: Readonly<{
  autoFocus?: boolean; value: string; onChange: (value: string) => void; disabled: boolean;
}>) {
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
  return <div className="operator-confirmation-field">
    <label><span>{t("researchers.code.label")}</span><input autoFocus={autoFocus} autoComplete="one-time-code" inputMode="numeric" pattern="[0-9]{6}" minLength={6} maxLength={6} required disabled={disabled || sending} value={value} onChange={event => onChange(event.target.value)} /></label>
    <button type="button" disabled={disabled || sending} onClick={() => void send()}>{sending ? t("researchers.code.sending") : sent ? t("researchers.code.resend") : t("researchers.code.send")}</button>
    {message ? <p role="status">{t(`researchers.code.${message}`)}</p> : null}
  </div>;
}
