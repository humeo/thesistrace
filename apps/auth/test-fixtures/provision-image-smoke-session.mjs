import { randomUUID } from "node:crypto";
import { createRequire } from "node:module";

const { Client } = createRequire("/app/auth/package.json")("pg");

const authOrigin = process.env.THESISTRACE_AUTH_FIXTURE_AUTH_ORIGIN;
const resendOrigin = "http://resend-fake:8300";
const clientIp = process.argv[3] ?? "127.0.0.1";
const email = process.argv[2];

try {
  if (typeof email !== "string" || email.length === 0) {
    throw new Error("EMAIL_REQUIRED");
  }
  if (process.env.THESISTRACE_ENVIRONMENT !== "test") throw new Error("SESSION_PROVISION_REQUIRES_TEST_ENVIRONMENT");
  if (typeof authOrigin !== "string" || authOrigin.length === 0) {
    throw new Error("AUTH_FIXTURE_AUTH_ORIGIN_REQUIRED");
  }
  if (!/^\d{1,3}(?:\.\d{1,3}){3}$/.test(clientIp)) {
    throw new Error("CLIENT_IP_INVALID");
  }
  const publicOrigin = process.env.THESISTRACE_PUBLIC_ORIGIN;
  if (typeof publicOrigin !== "string" || publicOrigin.length === 0) {
    throw new Error("PUBLIC_ORIGIN_REQUIRED");
  }

  await expectStatus(
    fetch(`${resendOrigin}/__test/emails`, { method: "DELETE" }),
    200,
    "RESEND_CLEAR_FAILED",
  );
  await expectStatus(fetch(`${authOrigin}/api/auth/email-otp/send-verification-otp`, {
    method: "POST", headers: {"content-type": "application/json", origin: publicOrigin, "x-thesistrace-client-ip": clientIp},
    body: JSON.stringify({email, type: "sign-in", captcha_token: `test-turnstile:${new URL(publicOrigin).hostname}:${Date.now()}:${randomUUID()}`}),
  }), 200, "EMAIL_CODE_SEND_FAILED");
  const otp = await awaitEmailCode();
  const accepted = await fetch(
    `${authOrigin}/api/auth/sign-in/email-otp`,
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        origin: publicOrigin,
        "x-thesistrace-client-ip": clientIp,
      },
      body: JSON.stringify({ email, otp }),
    },
  );
  if (accepted.status !== 200) {
    throw new Error("EMAIL_CODE_SIGN_IN_FAILED");
  }
  const cookie = accepted.headers
    .getSetCookie()
    .map((header) => header.split(";", 1)[0]?.trim())
    .filter((value) => typeof value === "string" && value.includes("="))
    .join("; ");
  if (cookie.length === 0) {
    throw new Error("SESSION_COOKIE_MISSING");
  }

  const verified = await fetch(`${authOrigin}/internal/session/verify`, {
    method: "POST",
    headers: { cookie },
  });
  if (verified.status !== 200) {
    throw new Error("SESSION_VERIFY_FAILED");
  }
  const body = await verified.json();
  if (
    body === null ||
    typeof body !== "object" ||
    typeof body.researcher_id !== "string"
  ) {
    throw new Error("SESSION_RESEARCHER_INVALID");
  }
  await resetTestRateLimits();
  process.stdout.write(
    `${JSON.stringify({ cookie, researcher_id: body.researcher_id })}\n`,
  );
} catch (error) {
  const code = error instanceof Error ? error.message : "SESSION_PROVISION_FAILED";
  process.stderr.write(`${JSON.stringify({ code, status: "failed" })}\n`);
  process.exitCode = 1;
}

async function resetTestRateLimits() {
  if (process.env.THESISTRACE_ENVIRONMENT !== "test") {
    throw new Error("RATE_LIMIT_RESET_REQUIRES_TEST_ENVIRONMENT");
  }
  const client = new Client({ connectionString: process.env.THESISTRACE_AUTH_DATABASE_URL });
  try {
    await client.connect();
    await client.query('DELETE FROM auth."rateLimit"');
  } finally {
    await client.end();
  }
}

async function expectStatus(responsePromise, expected, code) {
  const response = await responsePromise;
  if (response.status !== expected) {
    throw new Error(code);
  }
}

async function awaitEmailCode() {
  const deadline = Date.now() + 10_000;
  let sawEmail = false;
  while (Date.now() < deadline) {
    const response = await fetch(`${resendOrigin}/__test/emails`);
    if (response.status === 200) {
      const payload = await response.json();
      const emails = payload?.emails;
      if (Array.isArray(emails) && emails.length > 0) {
        sawEmail = true;
        const text = emails.at(-1)?.text;
        const match =
          typeof text === "string" ? /\b[0-9]{6}\b/.exec(text) : null;
        if (match !== null) {
          return match[0];
        }
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error(sawEmail ? "EMAIL_CODE_INVALID" : "EMAIL_CODE_EMAIL_MISSING");
}
