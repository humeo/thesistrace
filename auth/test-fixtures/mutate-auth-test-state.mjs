import { createRequire } from "node:module";

const require = createRequire("/app/auth/package.json");
const { Pool } = require("pg");

main().catch(() => {
  process.stderr.write(
    `${JSON.stringify({ code: "AUTH_TEST_STATE_MUTATION_FAILED" })}\n`,
  );
  process.exitCode = 1;
});

async function main() {
  if (process.env.THESISTRACE_ENVIRONMENT !== "test") {
    throw new Error("AUTH_TEST_STATE_MUTATION_FORBIDDEN");
  }
  if (process.argv.length !== 3) {
    throw new Error("AUTH_TEST_STATE_MUTATION_INVALID");
  }
  const command = process.argv[2];
  if (command === "reset-rate-limits") {
    await resetRateLimits();
    return;
  }
  if (command !== "expire-invitation") {
    throw new Error("AUTH_TEST_STATE_MUTATION_INVALID");
  }
  await expireInvitation();
}

async function expireInvitation() {
  const token = (await readStandardInput()).trim();
  const invitationId = token.split(".", 1)[0];
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(invitationId)) {
    throw new Error("AUTH_TEST_INVITATION_INVALID");
  }
  const databaseUrl = process.env.THESISTRACE_AUTH_DATABASE_URL;
  if (databaseUrl === undefined) {
    throw new Error("AUTH_TEST_DATABASE_UNAVAILABLE");
  }
  const pool = new Pool({ connectionString: databaseUrl, max: 1 });
  try {
    const result = await pool.query(
      `
        UPDATE auth.researcher_invitation
        SET expires_at = clock_timestamp() - INTERVAL '1 second'
        WHERE id = $1 AND status = 'delivered'
      `,
      [invitationId],
    );
    if (result.rowCount !== 1) {
      throw new Error("AUTH_TEST_INVITATION_NOT_FOUND");
    }
    process.stdout.write(`${JSON.stringify({ status: "expired" })}\n`);
  } finally {
    await pool.end();
  }
}

async function resetRateLimits() {
  const databaseUrl = process.env.THESISTRACE_AUTH_DATABASE_URL;
  if (databaseUrl === undefined) {
    throw new Error("AUTH_TEST_DATABASE_UNAVAILABLE");
  }
  const pool = new Pool({ connectionString: databaseUrl, max: 1 });
  try {
    await pool.query('DELETE FROM auth."rateLimit"');
    process.stdout.write(`${JSON.stringify({ status: "reset" })}\n`);
  } finally {
    await pool.end();
  }
}

async function readStandardInput() {
  const chunks = [];
  let size = 0;
  for await (const chunk of process.stdin) {
    size += chunk.length;
    if (size > 1024) throw new Error("AUTH_TEST_INPUT_TOO_LARGE");
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString("utf8");
}
