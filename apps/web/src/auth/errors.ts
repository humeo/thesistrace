/** Public authentication outcomes. Keep language out of auth state and callbacks. */
export type AuthErrorCode = "accountInactive" | "tooManyAttempts" | "unavailable" | "invalidCode"
  | "tooManyRequests" | "codeDeliveryFailed" | "signOutFailed" | "invitationExpired"
  | "invalidInvitation" | "passwordMismatch" | "operationFailed";

export type AuthFailure = Readonly<{ ok: false; code: AuthErrorCode; retryAfterSeconds?: number }>;
export type AuthResult = Readonly<{ ok: true }> | AuthFailure;
export type InvitationInspection = Readonly<{ ok: true; email: string }>
  | AuthFailure;

/** The current authentication contract uses integer seconds and 60-second windows. */
export function authRetryAfter(response: Response): number | null {
  const raw = response.headers.get("Retry-After");
  if (raw === null || !/^[1-9][0-9]*$/.test(raw)) return null;
  const seconds = Number(raw);
  return Number.isSafeInteger(seconds) && seconds <= 60 ? seconds : null;
}
