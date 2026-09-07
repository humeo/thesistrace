import { sha256 } from "./security.js";

const RESET_IDENTIFIER_PREFIX = "reset-password:";

export function passwordResetIdentifier(token: string): string {
  return `${RESET_IDENTIFIER_PREFIX}${sha256(token).toString("hex")}`;
}

export function rawPasswordResetToken(identifier: string): string | null {
  if (!identifier.startsWith(RESET_IDENTIFIER_PREFIX)) return null;
  const token = identifier.slice(RESET_IDENTIFIER_PREFIX.length);
  return token.length === 0 ? null : token;
}
