import type { ThesisTraceAuth } from "./auth.js";
import type { CredentialOperationCoordinator } from "./coordination.js";
import { canonicalizeEmail } from "./identity.js";
import type { ResendEmail } from "./resend.js";

/** Await provider acceptance: never show a sent state for failed delivery. */
export class EmailCodeDelivery {
  constructor(private readonly dependencies: Readonly<{
    auth: ThesisTraceAuth;
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
          html: `<p>Use <strong>${otp}</strong> to ${purpose}.</p><p>This code expires in 5 minutes.</p>`,
        });
      } catch {
        await context.internalAdapter.deleteVerificationByIdentifier(identifier);
        throw new Error("EMAIL_CODE_DELIVERY_FAILED");
      }
    });
  }
}
