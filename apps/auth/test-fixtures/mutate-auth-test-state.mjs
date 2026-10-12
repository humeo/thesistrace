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
  if (command === "seed-operator-directory") {
    await seedOperatorDirectory();
    return;
  }
  throw new Error("AUTH_TEST_STATE_MUTATION_INVALID");
}

async function seedOperatorDirectory() {
  const databaseUrl = process.env.THESISTRACE_AUTH_DATABASE_URL;
  if (databaseUrl === undefined) {
    throw new Error("AUTH_TEST_DATABASE_UNAVAILABLE");
  }
  const pool = new Pool({ connectionString: databaseUrl, max: 1 });
  try {
    const researchers = await pool.query(`
      INSERT INTO auth."user" (
        id, name, email, "emailVerified", "createdAt", "updatedAt", active
      )
      SELECT
        pg_catalog.format(
          '00000000-0000-4000-8100-%s',
          pg_catalog.lpad(seed.index::text, 12, '0')
        )::uuid,
        pg_catalog.format(
          'Paging Researcher %s',
          pg_catalog.lpad(seed.index::text, 2, '0')
        ),
        pg_catalog.format(
          'browser-page-%s@example.test',
          pg_catalog.lpad(seed.index::text, 2, '0')
        ),
        TRUE,
        TIMESTAMPTZ '2026-08-29T12:00:00.000Z',
        TIMESTAMPTZ '2026-08-29T12:00:00.000Z',
        TRUE
      FROM pg_catalog.generate_series(1, 55) AS seed(index)
    `);
    if (researchers.rowCount !== 55) {
      throw new Error("AUTH_TEST_OPERATOR_DIRECTORY_SEED_FAILED");
    }
    process.stdout.write(`${JSON.stringify({
      researchers: 55,
      status: "seeded",
    })}\n`);
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
