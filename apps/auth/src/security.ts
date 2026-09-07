import {
  createHash,
  createHmac,
  randomBytes,
  timingSafeEqual,
} from "node:crypto";

import { z } from "zod";

const tokenIdSchema = z.uuid();
const TOKEN_BYTES = 32;
const TOKEN_SECRET_LENGTH = 43;
const invalidHash = Buffer.alloc(TOKEN_BYTES);

export type ParsedOpaqueToken = Readonly<{
  hash: Buffer;
  id: string;
  secret: Buffer;
}>;

export function createOpaqueToken(
  id: string,
  random: (size: number) => Buffer = randomBytes,
): string {
  const parsedId = tokenIdSchema.parse(id);
  const secret = random(TOKEN_BYTES);
  if (secret.length !== TOKEN_BYTES) {
    throw new Error("OPAQUE_TOKEN_RANDOM_INVALID");
  }
  return `${parsedId}.${secret.toString("base64url")}`;
}

export function parseOpaqueToken(token: string): ParsedOpaqueToken | null {
  const separator = token.indexOf(".");
  if (separator < 0 || token.indexOf(".", separator + 1) >= 0) {
    return null;
  }
  const id = token.slice(0, separator);
  const encodedSecret = token.slice(separator + 1);
  if (
    !tokenIdSchema.safeParse(id).success ||
    encodedSecret.length !== TOKEN_SECRET_LENGTH ||
    !/^[A-Za-z0-9_-]+$/.test(encodedSecret)
  ) {
    return null;
  }
  const secret = Buffer.from(encodedSecret, "base64url");
  if (
    secret.length !== TOKEN_BYTES ||
    secret.toString("base64url") !== encodedSecret
  ) {
    return null;
  }
  return { hash: sha256(token), id, secret };
}

export function tokenHashMatches(
  storedHash: Buffer,
  candidateHash: Buffer | undefined,
): boolean {
  const storedValid = storedHash.length === TOKEN_BYTES;
  const candidateValid = candidateHash?.length === TOKEN_BYTES;
  const stored = storedValid ? storedHash : invalidHash;
  const candidate = candidateValid ? candidateHash : invalidHash;
  return storedValid && candidateValid && timingSafeEqual(stored, candidate);
}

export function unknownEmailHmac(secret: string, email: string): Buffer {
  return createHmac("sha256", secret).update(email, "utf8").digest();
}

export function secretFingerprint(secret: string): string {
  return createHash("sha256").update(secret, "utf8").digest("hex");
}

export function sha256(value: string): Buffer {
  return createHash("sha256").update(value, "utf8").digest();
}
