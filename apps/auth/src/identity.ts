import { z } from "zod";

import { isJsonContentType } from "./http-media-type.js";

const canonicalEmailSchema = z
  .string()
  .trim()
  .toLowerCase()
  .max(254)
  .pipe(z.email());

const emailRequestPaths = new Set([
  "/api/auth/sign-in/email-otp",
  "/api/auth/email-otp/send-verification-otp",
  "/api/auth/change-email",
  "/api/auth/request-password-reset",
  "/api/auth/send-verification-email",
  "/api/auth/sign-in/email",
]);

export class InvalidEmailError extends Error {
  constructor() {
    super("EMAIL_INVALID");
    this.name = "InvalidEmailError";
  }
}

export function canonicalizeEmail(value: string): string {
  const parsed = canonicalEmailSchema.safeParse(value);
  if (!parsed.success) {
    throw new InvalidEmailError();
  }
  return parsed.data;
}

export async function canonicalizeAuthEmailRequest(
  request: Request,
): Promise<Request | Response> {
  const path = new URL(request.url).pathname;
  if (
    request.method !== "POST" ||
    !emailRequestPaths.has(path) ||
    !isJsonContentType(request.headers.get("content-type"))
  ) {
    return request;
  }

  let body: unknown;
  try {
    body = await request.clone().json();
  } catch {
    return request;
  }
  if (!isRecord(body) || typeof body.email !== "string") {
    return request;
  }

  let email: string;
  try {
    email = canonicalizeEmail(body.email);
  } catch (error) {
    if (error instanceof InvalidEmailError) {
      return Response.json({ code: "INVALID_EMAIL" }, { status: 400 });
    }
    throw error;
  }

  const headers = new Headers(request.headers);
  headers.delete("content-length");
  return new Request(request, {
    body: JSON.stringify({ ...body, email }),
    headers,
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
