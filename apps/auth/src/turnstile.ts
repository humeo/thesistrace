import { z } from "zod";
import { SIGN_IN_CHALLENGE_ACTION } from "./sign-in-code-admission.js";

export const TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify";
const verificationSchema = z.object({success: z.boolean(), hostname: z.string().optional(), action: z.string().optional()});

/** Cloudflare owns token expiry and single-use validation; bind it to this form. */
export function createTurnstileVerifier(settings: Readonly<{
  secretKey: string;
  publicOrigin: string;
  verifyUrl: string;
}>, fetcher: typeof fetch = fetch) {
  const hostname = new URL(settings.publicOrigin).hostname;
  return async (token: string, remoteIp: string): Promise<boolean> => {
    if (!token || token.length > 2048) return false;
    const response = await fetcher(settings.verifyUrl, {
      method: "POST",
      headers: {"content-type": "application/x-www-form-urlencoded"},
      body: new URLSearchParams({secret: settings.secretKey, response: token, remoteip: remoteIp}),
      signal: AbortSignal.timeout(5000),
      redirect: "error",
    });
    if (!response.ok) throw new Error("AUTH_CHALLENGE_UNAVAILABLE");
    const result = verificationSchema.parse(await response.json());
    return result.success && result.hostname === hostname && result.action === SIGN_IN_CHALLENGE_ACTION;
  };
}
