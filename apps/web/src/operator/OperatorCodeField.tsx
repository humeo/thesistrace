import { useState } from "react";

export function OperatorCodeField({value, onChange, disabled, autoFocus = true}: Readonly<{
  autoFocus?: boolean; value: string; onChange: (value: string) => void; disabled: boolean;
}>) {
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  async function send() {
    if (sending || disabled) return;
    setSending(true); setMessage(null);
    try {
      const response = await fetch("/api/auth/operator/proofs/send-code", {
        method: "POST", credentials: "same-origin",
        headers: {"Content-Type": "application/json"}, body: "{}",
      });
      if (!response.ok) throw new Error("Code could not be sent. Please wait and try again.");
      onChange(""); setSent(true); setMessage("A code was sent to your account email. It expires in 5 minutes.");
    } catch { setMessage("Code could not be sent. Please wait and try again."); }
    finally { setSending(false); }
  }
  return <div className="operator-confirmation-field">
    <label><span>Verification code</span><input autoFocus={autoFocus} autoComplete="one-time-code" inputMode="numeric" pattern="[0-9]{6}" minLength={6} maxLength={6} required disabled={disabled || sending} value={value} onChange={event => onChange(event.target.value)} /></label>
    <button type="button" disabled={disabled || sending} onClick={() => void send()}>{sending ? "Sending…" : sent ? "Resend code" : "Send confirmation code"}</button>
    {message ? <p role="status">{message}</p> : null}
  </div>;
}
