const LOGIN_SESSION_COOKIE_NAMES = [
  "__Secure-thesistrace.session_token",
  "thesistrace.session_token",
] as const;

/** Return exactly one Better Auth Login Session Cookie and discard all others. */
export function loginSessionCookieHeader(cookieHeader: string | null): string | undefined {
  if (cookieHeader === null) return undefined;
  const pairs = cookieHeader.split(";").map((pair) => pair.trim());
  for (const name of LOGIN_SESSION_COOKIE_NAMES) {
    const prefix = `${name}=`;
    const selected = pairs.find((pair) => pair.startsWith(prefix));
    if (selected !== undefined && selected.length > prefix.length) return selected;
  }
  return undefined;
}
