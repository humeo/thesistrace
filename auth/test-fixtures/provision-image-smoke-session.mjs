import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";

const { Client } = createRequire("/app/auth/package.json")("pg");

const authOrigin = process.env.THESISTRACE_AUTH_FIXTURE_AUTH_ORIGIN;
const resendOrigin = "http://resend-fake:8300";
const password = process.argv[3] ?? "correct-horse-battery-staple";
const clientIp = process.argv[4] ?? "127.0.0.1";
const email = process.argv[2];

try {
  if (typeof email !== "string" || email.length === 0) {
    throw new Error("EMAIL_REQUIRED");
  }
  if (password.length < 12 || password.length > 128) {
    throw new Error("PASSWORD_INVALID");
  }
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
  const invitation = spawnSync(
    process.execPath,
    ["dist/operator.js", "invite", "--email", email],
    {
      cwd: "/app/auth",
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  if (invitation.status !== 0) {
    throw new Error("INVITATION_FAILED");
  }

  const token = await awaitInvitationToken();
  const accepted = await fetch(
    `${authOrigin}/api/auth/researcher-invitation/accept`,
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        origin: publicOrigin,
        "x-thesistrace-client-ip": clientIp,
      },
      body: JSON.stringify({ token, password }),
    },
  );
  if (accepted.status !== 200) {
    throw new Error("INVITATION_ACCEPT_FAILED");
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

async function awaitInvitationToken() {
  const deadline = Date.now() + 10_000;
  let sawEmail = false;
  while (Date.now() < deadline) {
    const response = await fetch(`${resendOrigin}/__test/emails`);
    if (response.status === 200) {
      const payload = await response.json();
      const emails = payload?.emails;
      if (Array.isArray(emails) && emails.length > 0) {
        sawEmail = true;
        const html = emails.at(-1)?.html;
        const match =
          typeof html === "string" ? /#token=([^"'<\s]+)/.exec(html) : null;
        if (match !== null) {
          return decodeURIComponent(match[1]);
        }
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error(sawEmail ? "INVITATION_TOKEN_INVALID" : "INVITATION_EMAIL_MISSING");
}
