import type { ThesisTraceAuth } from "../src/auth.js";

/** Provision test identities through the current library contract without consuming HTTP quotas. */
export async function emailSession(auth: ThesisTraceAuth, email: string, headers?: Headers): Promise<Response> {
  const otp = await auth.api.createVerificationOTP({body: {email: email.trim().toLowerCase(), type: "sign-in"}});
  return auth.api.signInEmailOTP({body: {email, otp}, headers, asResponse: true});
}
