/** Public authentication outcomes. Keep language out of auth state and callbacks. */
export type AuthErrorCode = "accountInactive" | "tooManyAttempts" | "unavailable" | "invalidCode"
  | "tooManyRequests" | "codeDeliveryFailed" | "signOutFailed" | "invitationExpired"
  | "invalidInvitation" | "passwordMismatch" | "operationFailed";

export type AuthResult = Readonly<{ ok: true }> | Readonly<{ ok: false; code: AuthErrorCode }>;
export type InvitationInspection = Readonly<{ ok: true; email: string }>
  | Readonly<{ ok: false; code: AuthErrorCode }>;
