import { generateKeyPairSync, randomBytes, randomUUID } from "node:crypto";
import { lstatSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseEnv } from "node:util";
import { spawnSync } from "node:child_process";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const file = resolve(process.env.THESISTRACE_ENV_FILE ?? resolve(root, ".env"));
const template = readFileSync(resolve(root, ".env.example"), "utf8");
const knownNames = new Set(Object.keys(parseEnv(template)));

function fail(code, names = []) {
  process.stderr.write(`${JSON.stringify({ code, variables: names })}\n`);
  process.exit(2);
}

function readConfiguration() {
  let source;
  try {
    const metadata = lstatSync(file);
    if (!metadata.isFile() || (metadata.mode & 0o777) !== 0o600) {
      fail("CONFIG_FILE_PERMISSIONS_INVALID");
    }
    source = readFileSync(file, "utf8");
  } catch {
    fail("CONFIG_FILE_MISSING_RUN_CONFIG_INIT");
  }
  const seen = new Set();
  for (const line of source.split("\n")) {
    if (!line.trim() || line.trimStart().startsWith("#")) continue;
    const match = /^([A-Z][A-Z0-9_]*)=(.*)$/.exec(line);
    if (!match) fail("CONFIG_FILE_SYNTAX_INVALID");
    const [, name, value] = match;
    if (!knownNames.has(name)) fail("CONFIG_VARIABLE_UNKNOWN", [name]);
    if (seen.has(name)) fail("CONFIG_VARIABLE_DUPLICATED", [name]);
    seen.add(name);
    if (value !== value.trim() || /^["']/.test(value) || /[\r$#\x00]/.test(value)) {
      fail("CONFIG_LITERAL_REQUIRED", [name]);
    }
  }
  return parseEnv(source);
}

function check() {
  const values = readConfiguration();
  const required = new Set();
  for (const name of ["compose.yaml", "compose.dev.yaml"]) {
    const source = readFileSync(resolve(root, "deploy/core", name), "utf8");
    for (const match of source.matchAll(/\$\{([A-Z][A-Z0-9_]*):\?/g)) {
      if (match[1] !== "THESISTRACE_AGENT_MODEL_REGISTRY") required.add(match[1]);
    }
  }
  const registry = JSON.parse(readFileSync(resolve(root, "config/model-registry.json"), "utf8"));
  for (const model of registry.models) {
    if (model.enabled) required.add(model.secret_env);
  }
  const missing = [...required].filter((name) => !values[name]).sort();
  if (missing.length) fail("CONFIG_VALUE_MISSING", missing);
  if (values.THESISTRACE_ENVIRONMENT !== "development") {
    fail("CONFIG_DEVELOPMENT_REQUIRED", ["THESISTRACE_ENVIRONMENT"]);
  }
  const token = values.THESISTRACE_TUSHARE_TOKEN;
  if (token.length < 8 || token.length > 512 || /\s/.test(token)
    || /^(test-|development-|placeholder)/i.test(token)
    || /^(changeme|dummy|example|tushare-test-token)$/i.test(token)
    || /^<.*>$/.test(token)) fail("CONFIG_CREDENTIAL_INVALID", ["THESISTRACE_TUSHARE_TOKEN"]);
  return values;
}

function initialize() {
  const generated = {};
  for (const name of [
    "THESISTRACE_OWNER_DATABASE_PASSWORD", "THESISTRACE_CORE_DATABASE_PASSWORD",
    "THESISTRACE_AUTH_DATABASE_PASSWORD", "THESISTRACE_AGENT_DATABASE_PASSWORD",
    "THESISTRACE_S3_SECRET_ACCESS_KEY", "BETTER_AUTH_SECRET",
    "THESISTRACE_DEV_RESEARCHER_PASSWORD",
  ]) generated[name] = randomBytes(32).toString("hex");
  generated.THESISTRACE_S3_ACCESS_KEY_ID = randomBytes(16).toString("hex");
  const { privateKey, publicKey } = generateKeyPairSync("ed25519");
  const privateJwk = privateKey.export({ format: "jwk" });
  const publicJwk = publicKey.export({ format: "jwk" });
  const kid = `development-${randomUUID()}`;
  generated.THESISTRACE_MCP_SIGNING_PRIVATE_JWK = JSON.stringify({
    alg: "EdDSA", crv: privateJwk.crv, d: privateJwk.d, kid,
    kty: privateJwk.kty, use: "sig", x: privateJwk.x,
  });
  generated.THESISTRACE_MCP_VERIFYING_PUBLIC_JWK = JSON.stringify({
    alg: "EdDSA", crv: publicJwk.crv, kid, kty: publicJwk.kty, use: "sig", x: publicJwk.x,
  });
  const content = template.replace(/^([A-Z][A-Z0-9_]*)=.*$/gm,
    (line, name) => generated[name] === undefined ? line : `${name}=${generated[name]}`);
  try {
    writeFileSync(file, content, { flag: "wx", mode: 0o600 });
  } catch (error) {
    fail(error.code === "EEXIST" ? "CONFIG_FILE_ALREADY_EXISTS" : "CONFIG_FILE_WRITE_FAILED");
  }
  process.stdout.write("Created private configuration. Fill external credentials, then run pnpm config:check.\n");
}

try {
  const [action, ...extra] = process.argv.slice(2);
  if (action === "run") {
    const args = extra[0] === "--" ? extra.slice(1) : extra;
    if (!args.length) fail("CONFIG_USAGE_INVALID");
    const values = check();
    const environment = { ...process.env };
    for (const name of knownNames) delete environment[name];
    const result = spawnSync(args[0], args.slice(1), {
      stdio: "inherit",
      env: { ...environment, ...values,
        THESISTRACE_AGENT_MODEL_REGISTRY: readFileSync(resolve(root, "config/model-registry.json"), "utf8") },
    });
    if (result.error) fail("CONFIG_COMMAND_FAILED");
    process.exit(result.status ?? 1);
  } else if (extra.length) fail("CONFIG_USAGE_INVALID");
  else if (action === "init") initialize();
  else if (action === "check") check();
  else fail("CONFIG_USAGE_INVALID");
} catch {
  fail("CONFIG_INVALID");
}
