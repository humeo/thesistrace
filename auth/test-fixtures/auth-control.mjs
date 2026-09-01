import { execFile } from "node:child_process";
import http from "node:http";
import { createRequire } from "node:module";
import { promisify } from "node:util";

if (process.env.THESISTRACE_ENVIRONMENT !== "test") {
  throw new Error("Auth fixture control requires the Test environment");
}

const { Pool } = createRequire("/app/auth/package.json")("pg");
const executeFile = promisify(execFile);
const port = requiredPort("THESISTRACE_AUTH_FIXTURE_CONTROL_PORT");
const databaseUrl = required("THESISTRACE_AUTH_DATABASE_URL");
const pool = new Pool({ connectionString: databaseUrl, max: 1 });
const operatorCommands = new Set([
  "deactivate",
  "invite",
  "reactivate",
  "reissue",
  "revoke-sessions",
]);

const server = http.createServer(async (request, response) => {
  const url = new URL(request.url ?? "/", "http://auth-fixture-control.test");
  if (request.method === "GET" && url.pathname === "/health/live") {
    json(response, 200, { status: "ok" });
    return;
  }
  if (request.method !== "POST" || url.search !== "") {
    json(response, 404, { code: "NOT_FOUND" });
    return;
  }

  try {
    const body = await readJson(request, 32 * 1024);
    if (body === null) {
      json(response, 400, { code: "AUTH_FIXTURE_INPUT_INVALID" });
      return;
    }
    if (url.pathname === "/__test/provision-session") {
      const result = await provisionSession(body);
      json(response, 200, result);
      return;
    }
    if (url.pathname === "/__test/operator") {
      const result = await runOperator(body);
      json(response, 200, result);
      return;
    }
    if (url.pathname === "/__test/expire-invitation") {
      await expireInvitation(body);
      json(response, 200, { status: "expired" });
      return;
    }
    if (url.pathname === "/__test/reset-rate-limits") {
      if (Object.keys(body).length !== 0) {
        json(response, 400, { code: "AUTH_FIXTURE_INPUT_INVALID" });
        return;
      }
      await pool.query('DELETE FROM auth."rateLimit"');
      json(response, 200, { status: "reset" });
      return;
    }
    json(response, 404, { code: "NOT_FOUND" });
  } catch {
    json(response, 500, { code: "AUTH_FIXTURE_COMMAND_FAILED" });
  }
});

server.listen(port, "0.0.0.0");

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.once(signal, () => {
    server.close(() => {
      void pool.end().finally(() => process.exit(0));
    });
  });
}

async function provisionSession(body) {
  const email = validEmail(body.email);
  const password = body.password;
  const clientIp = body.client_ip;
  if (
    typeof password !== "string"
    || password.length < 12
    || password.length > 128
    || typeof clientIp !== "string"
    || !/^\d{1,3}(?:\.\d{1,3}){3}$/.test(clientIp)
  ) {
    throw new Error("AUTH_FIXTURE_INPUT_INVALID");
  }
  const { stdout } = await executeFile(
    process.execPath,
    [
      "/test-fixtures/provision-image-smoke-session.mjs",
      email,
      password,
      clientIp,
    ],
    commandOptions(),
  );
  return parsedObject(stdout);
}

async function runOperator(body) {
  const args = body.args;
  if (
    !Array.isArray(args)
    || args.length !== 3
    || typeof args[0] !== "string"
    || !operatorCommands.has(args[0])
    || args[1] !== "--email"
  ) {
    throw new Error("AUTH_FIXTURE_INPUT_INVALID");
  }
  const email = validEmail(args[2]);
  const { stdout } = await executeFile(
    process.execPath,
    ["dist/operator.js", args[0], "--email", email],
    commandOptions(),
  );
  return parsedObject(stdout);
}

async function expireInvitation(body) {
  if (typeof body.token !== "string" || body.token.length > 1024) {
    throw new Error("AUTH_FIXTURE_INPUT_INVALID");
  }
  const invitationId = body.token.split(".", 1)[0];
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(invitationId)) {
    throw new Error("AUTH_FIXTURE_INPUT_INVALID");
  }
  const result = await pool.query(
    `
      UPDATE auth.researcher_invitation
      SET expires_at = clock_timestamp() - INTERVAL '1 second'
      WHERE id = $1 AND status = 'delivered'
    `,
    [invitationId],
  );
  if (result.rowCount !== 1) {
    throw new Error("AUTH_FIXTURE_INVITATION_NOT_FOUND");
  }
}

function commandOptions() {
  return {
    cwd: "/app/auth",
    encoding: "utf8",
    env: process.env,
    maxBuffer: 8 * 1024 * 1024,
    timeout: 30_000,
  };
}

function parsedObject(output) {
  const value = JSON.parse(output);
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("AUTH_FIXTURE_OUTPUT_INVALID");
  }
  return value;
}

function validEmail(value) {
  if (
    typeof value !== "string"
    || value.length > 320
    || !/^[^\s@]+@[^\s@]+$/.test(value)
  ) {
    throw new Error("AUTH_FIXTURE_INPUT_INVALID");
  }
  return value;
}

async function readJson(request, maxBytes) {
  const chunks = [];
  let bytes = 0;
  for await (const chunk of request) {
    bytes += chunk.length;
    if (bytes > maxBytes) return null;
    chunks.push(chunk);
  }
  try {
    const value = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    return value !== null && typeof value === "object" && !Array.isArray(value)
      ? value
      : null;
  } catch {
    return null;
  }
}

function json(response, status, body) {
  response.writeHead(status, {
    "cache-control": "no-store",
    "content-type": "application/json",
  });
  response.end(JSON.stringify(body));
}

function required(name) {
  const value = process.env[name];
  if (value === undefined || value.length === 0) throw new Error(`${name} is required`);
  return value;
}

function requiredPort(name) {
  const value = Number(required(name));
  if (!Number.isSafeInteger(value) || value < 0 || value > 65_535) {
    throw new Error(`${name} must be a valid port`);
  }
  return value;
}
