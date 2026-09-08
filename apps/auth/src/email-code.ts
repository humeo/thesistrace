import type { ThesisTraceAuth } from "./auth.js";
import type { CredentialOperationCoordinator } from "./coordination.js";
import { canonicalizeEmail } from "./identity.js";
import type { ResendEmail } from "./resend.js";

/** Await provider acceptance: never show a sent state for failed delivery. */
export class EmailCodeDelivery {
  constructor(private readonly dependencies: Readonly<{
    auth: ThesisTraceAuth;
    publicOrigin: string;
    coordinator: CredentialOperationCoordinator;
    sendEmail: (email: ResendEmail) => Promise<void>;
  }>) {}

  async send(emailInput: string, type: "sign-in" | "email-verification"): Promise<void> {
    const email = canonicalizeEmail(emailInput);
    const {auth, coordinator, sendEmail} = this.dependencies;
    await coordinator.runForEmail(email, async () => {
      const context = await auth.$context;
      const identifier = `${type}-otp-${email}`;
      await context.internalAdapter.deleteVerificationByIdentifier(identifier);
      const otp = await auth.api.createVerificationOTP({body: {email, type}});
      const purpose = type === "sign-in" ? "sign in to QuantTrace" : "confirm your Operator action";
      try {
        await sendEmail({to: email, subject: "Your QuantTrace verification code",
          text: `Use ${otp} to ${purpose}. This code expires in 5 minutes.`,
          html: verificationCodeHtml(otp, purpose, this.dependencies.publicOrigin),
        });
      } catch {
        await context.internalAdapter.deleteVerificationByIdentifier(identifier);
        throw new Error("EMAIL_CODE_DELIVERY_FAILED");
      }
    });
  }
}

export function verificationCodeHtml(otp: string, purpose: string, publicOrigin: string): string {
  const escape = (value: string) => value.replace(/[&<>"']/g, character =>
    ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"})[character]!);
  return `<!doctype html>
<html lang="en"><head><meta name="viewport" content="width=device-width, initial-scale=1"><meta charset="utf-8"><title>Your QuantTrace verification code</title></head>
<body style="margin:0;padding:0;background:#f4f5f7;color:#17181b;font-family:Arial,Helvetica,sans-serif;">
<div style="display:none;max-height:0;overflow:hidden;">Your one-time code is ready. It expires in 5 minutes.</div>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr><td align="center" style="padding:32px 16px;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:480px;background:#ffffff;border:1px solid #e3e5e9;border-radius:12px;">
<tr><td style="padding:28px;border-bottom:1px solid #eceef1;">
<table role="presentation" cellspacing="0" cellpadding="0"><tr><td style="padding:6px;background:#010102;border-radius:8px;"><img src="${escape(new URL('/quanttrace-logo.png', publicOrigin).href)}" width="32" height="32" alt="" style="display:block;border:0;"></td><td style="padding-left:12px;font-size:20px;font-weight:700;letter-spacing:-0.5px;">QuantTrace</td></tr></table>
</td></tr>
<tr><td style="padding:28px;">
<h1 style="margin:0 0 12px;font-size:24px;line-height:1.3;letter-spacing:-0.5px;">Your verification code</h1>
<p style="margin:0 0 24px;color:#555b66;font-size:15px;line-height:1.6;">Use the code below to ${escape(purpose)}.</p>
<div style="padding:22px 8px;background:#f1f2fb;border:1px solid #dddff3;border-radius:8px;text-align:center;font-family:Consolas,Menlo,monospace;font-size:34px;line-height:1.4;font-weight:700;letter-spacing:8px;color:#303b8f;">${escape(otp)}</div>
<p style="margin:12px 0 0;text-align:center;color:#555b66;font-size:13px;line-height:1.5;">Select the code to copy it, then paste it into QuantTrace.</p>
<p style="margin:12px 0 28px;text-align:center;color:#555b66;font-size:13px;line-height:1.5;">Valid for <strong>5 minutes</strong>. Use this code only once.</p>
<p style="margin:0;padding-top:24px;border-top:1px solid #eceef1;color:#737984;font-size:13px;line-height:1.6;">Keep this code private. If you didn’t request it, you can ignore this email.</p>
</td></tr></table>
<p style="margin:20px 0 0;color:#737984;font-size:12px;">QuantTrace · Quantitative Research Workbench</p>
</td></tr></table></body></html>`;
}
