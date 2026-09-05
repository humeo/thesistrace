import { createPrivateKey, createPublicKey } from "node:crypto";
import { isIP } from "node:net";

import { z } from "zod";

import { AuthConfigurationError } from "./failure.js";

const runtimeEnvironmentSchema = z.enum(["development", "test", "production"]);
const mcpGrantScopeSchema = z.enum([
  "research:read",
  "research:execute",
  "tracking:read",
  "tracking:execute",
]);
const base64Url32ByteSchema = z.string().regex(/^[A-Za-z0-9_-]{43}$/);
const mcpPublicJwkSchema = z.object({
  alg: z.literal("EdDSA"),
  crv: z.literal("Ed25519"),
  kid: z.string().regex(/^[A-Za-z0-9_-]{8,128}$/),
  kty: z.literal("OKP"),
  use: z.literal("sig"),
  x: base64Url32ByteSchema,
}).strict();
const mcpPrivateJwkSchema = mcpPublicJwkSchema.extend({
  d: base64Url32ByteSchema,
}).strict();

export type McpGrantScope = z.infer<typeof mcpGrantScopeSchema>;
export type McpPublicJwk = Readonly<z.infer<typeof mcpPublicJwkSchema>>;
export type McpPrivateJwk = Readonly<z.infer<typeof mcpPrivateJwkSchema>>;

export type AuthSettings = Readonly<{
  databaseUrl: string;
  environment: z.infer<typeof runtimeEnvironmentSchema>;
  host: string;
  mcpAgentRunMaxWallSeconds: number;
  mcpAudience: string;
  mcpClientId: string;
  mcpClockSkewSeconds: number;
  mcpGrantScopes: readonly McpGrantScope[];
  mcpIssuer: string;
  mcpPrivateJwk: McpPrivateJwk;
  mcpPublicJwk: McpPublicJwk;
  mcpTokenLifetimeSeconds: number;
  port: number;
  publicOrigin: string;
  resendApiKey: string;
  resendApiUrl: string;
  resendFromEmail: string;
  secret: string;
  secureCookies: boolean;
}>;

export type AuthInitializerSettings = Readonly<{ databaseUrl: string }>;

type Environment = Readonly<Record<string, string | undefined>>;

const unsupportedBetterAuthEnvironmentNames = [
  "BETTER_AUTH_SECRETS",
  "BETTER_AUTH_TELEMETRY",
  "BETTER_AUTH_TELEMETRY_DEBUG",
  "BETTER_AUTH_TELEMETRY_ENDPOINT",
  "BETTER_AUTH_TELEMETRY_ID",
  "BETTER_AUTH_TRUSTED_ORIGINS",
] as const;

export function readAuthSettings(environment: Environment = process.env): AuthSettings {
  assertNoAmbientBetterAuthOverrides(environment);
  const runtimeEnvironment = required(environment, "THESISTRACE_ENVIRONMENT");
  const parsedEnvironment = runtimeEnvironmentSchema.safeParse(runtimeEnvironment);
  if (!parsedEnvironment.success) {
    throw new AuthConfigurationError(
      "THESISTRACE_ENVIRONMENT must be development, test, or production",
    );
  }

  const publicOrigin = parsePublicOrigin(
    required(environment, "THESISTRACE_PUBLIC_ORIGIN"),
    parsedEnvironment.data,
  );
  const databaseUrl = parseDatabaseUrl(
    required(environment, "THESISTRACE_AUTH_DATABASE_URL"),
    "THESISTRACE_AUTH_DATABASE_URL",
    "auth_runtime",
  );
  const secret = parseSecret(
    required(environment, "BETTER_AUTH_SECRET"),
    parsedEnvironment.data,
  );
  const mcpIssuer = parseMcpIssuer(
    required(environment, "THESISTRACE_MCP_ISSUER_URL"), parsedEnvironment.data !== "production",
  );
  const mcpAudience = parseMcpAudience(
    required(environment, "THESISTRACE_MCP_RESOURCE_URL"), parsedEnvironment.data !== "production",
  );
  if (mcpIssuer !== `${publicOrigin}/api/auth`) {
    throw new AuthConfigurationError("THESISTRACE_MCP_ISSUER_URL must match THESISTRACE_PUBLIC_ORIGIN/api/auth");
  }
  const mcpClientId = parseMcpClientId(
    required(environment, "THESISTRACE_MCP_CLIENT_ID"),
  );
  const mcpGrantScopes = parseMcpGrantScopes(
    required(environment, "THESISTRACE_MCP_AGENT_SCOPES"),
  );
  const mcpPrivateJwk = parseJson(
    required(environment, "THESISTRACE_MCP_SIGNING_PRIVATE_JWK"),
    mcpPrivateJwkSchema,
    "THESISTRACE_MCP_SIGNING_PRIVATE_JWK",
  );
  const mcpPublicJwk = parseJson(
    required(environment, "THESISTRACE_MCP_VERIFYING_PUBLIC_JWK"),
    mcpPublicJwkSchema,
    "THESISTRACE_MCP_VERIFYING_PUBLIC_JWK",
  );
  assertMatchingMcpKeys(mcpPrivateJwk, mcpPublicJwk);
  const mcpTokenLifetimeSeconds = parsePositiveInteger(
    required(environment, "THESISTRACE_MCP_ACCESS_TOKEN_TTL_SECONDS"),
    "THESISTRACE_MCP_ACCESS_TOKEN_TTL_SECONDS",
  );
  const mcpAgentRunMaxWallSeconds = parsePositiveInteger(
    required(environment, "THESISTRACE_AGENT_RUN_MAX_WALL_SECONDS"),
    "THESISTRACE_AGENT_RUN_MAX_WALL_SECONDS",
  );
  const mcpClockSkewSeconds = parseNonnegativeInteger(
    required(environment, "THESISTRACE_MCP_CLOCK_SKEW_SECONDS"),
    "THESISTRACE_MCP_CLOCK_SKEW_SECONDS",
  );
  if (
    mcpTokenLifetimeSeconds
      <= mcpAgentRunMaxWallSeconds + mcpClockSkewSeconds
  ) {
    throw new AuthConfigurationError(
      "THESISTRACE_MCP_ACCESS_TOKEN_TTL_SECONDS must exceed the Agent Run wall time plus MCP clock skew",
    );
  }
  const resendApiKey = parseResendApiKey(required(environment, "RESEND_API_KEY"));
  const resendFromEmail = parseResendFromEmail(
    required(environment, "RESEND_FROM_EMAIL"),
  );
  const resendApiUrl = parseResendApiUrl(
    required(environment, "THESISTRACE_RESEND_API_URL"),
    parsedEnvironment.data,
  );
  const port = parsePort(environment.THESISTRACE_AUTH_PORT ?? "8200");

  return {
    databaseUrl,
    environment: parsedEnvironment.data,
    host: environment.THESISTRACE_AUTH_HOST ?? "0.0.0.0",
    mcpAgentRunMaxWallSeconds,
    mcpAudience,
    mcpClientId,
    mcpClockSkewSeconds,
    mcpGrantScopes,
    mcpIssuer,
    mcpPrivateJwk,
    mcpPublicJwk,
    mcpTokenLifetimeSeconds,
    port,
    publicOrigin,
    resendApiKey,
    resendApiUrl,
    resendFromEmail,
    secret,
    secureCookies: parsedEnvironment.data === "production",
  };
}

function parseMcpIssuer(value: string, allowLoopback: boolean): string {
  return parseCanonicalHttpsUrl(value, "THESISTRACE_MCP_ISSUER_URL", false, allowLoopback);
}

function parseMcpAudience(value: string, allowLoopback: boolean): string {
  const canonical = parseCanonicalHttpsUrl(
    value,
    "THESISTRACE_MCP_RESOURCE_URL",
    true, allowLoopback,
  );
  if (new URL(canonical).pathname !== "/mcp") {
    throw new AuthConfigurationError(
      "THESISTRACE_MCP_RESOURCE_URL must identify the canonical /mcp resource",
    );
  }
  return canonical;
}

function parseCanonicalHttpsUrl(
  value: string,
  variableName: string,
  rejectTrailingSlash: boolean,
  allowLoopback: boolean,
): string {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new AuthConfigurationError(`${variableName} must be a canonical HTTPS URL`);
  }
  if (
    (url.protocol !== "https:" && !(allowLoopback && url.protocol === "http:" && isLoopbackHostname(unbracketedHostname(url.hostname))))
    || url.username.length > 0
    || url.password.length > 0
    || url.search.length > 0
    || url.hash.length > 0
    || value !== url.toString()
    || (rejectTrailingSlash && url.pathname.endsWith("/"))
  ) {
    throw new AuthConfigurationError(`${variableName} must be a canonical HTTPS URL`);
  }
  return value;
}

function parseMcpClientId(value: string): string {
  if (!/^[a-z0-9][a-z0-9._-]{2,63}$/.test(value)) {
    throw new AuthConfigurationError(
      "THESISTRACE_MCP_CLIENT_ID must be one stable lowercase client identifier",
    );
  }
  return value;
}

function parseMcpGrantScopes(value: string): readonly McpGrantScope[] {
  const parsed = parseJson(
    value,
    z.array(mcpGrantScopeSchema).min(1).max(4),
    "THESISTRACE_MCP_AGENT_SCOPES",
  );
  if (new Set(parsed).size !== parsed.length) {
    throw new AuthConfigurationError(
      "THESISTRACE_MCP_AGENT_SCOPES cannot contain duplicate scopes",
    );
  }
  return parsed;
}

function parseJson<T>(
  value: string,
  schema: z.ZodType<T>,
  variableName: string,
): T {
  try {
    const parsed = schema.safeParse(JSON.parse(value));
    if (parsed.success) return parsed.data;
  } catch {
    // The one configuration error below deliberately hides the supplied value.
  }
  throw new AuthConfigurationError(`${variableName} is invalid`);
}

function assertMatchingMcpKeys(
  privateJwk: McpPrivateJwk,
  publicJwk: McpPublicJwk,
): void {
  let derivedPublicJwk: JsonWebKey;
  try {
    const privateKey = createPrivateKey({ key: privateJwk, format: "jwk" });
    derivedPublicJwk = createPublicKey(privateKey).export({ format: "jwk" });
  } catch {
    throw new AuthConfigurationError(
      "THESISTRACE_MCP_SIGNING_PRIVATE_JWK and THESISTRACE_MCP_VERIFYING_PUBLIC_JWK must be one key pair",
    );
  }
  const matches = (["alg", "crv", "kid", "kty", "use", "x"] as const)
    .every((field) => privateJwk[field] === publicJwk[field])
    && derivedPublicJwk.kty === "OKP"
    && derivedPublicJwk.crv === "Ed25519"
    && derivedPublicJwk.x === publicJwk.x;
  if (!matches) {
    throw new AuthConfigurationError(
      "THESISTRACE_MCP_SIGNING_PRIVATE_JWK and THESISTRACE_MCP_VERIFYING_PUBLIC_JWK must be one key pair",
    );
  }
}

function parsePositiveInteger(value: string, variableName: string): number {
  const parsed = parseNonnegativeInteger(value, variableName);
  if (parsed === 0) {
    throw new AuthConfigurationError(`${variableName} must be positive`);
  }
  return parsed;
}

function parseNonnegativeInteger(value: string, variableName: string): number {
  if (!/^(0|[1-9][0-9]*)$/.test(value)) {
    throw new AuthConfigurationError(`${variableName} must be an integer`);
  }
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed)) {
    throw new AuthConfigurationError(`${variableName} must be an integer`);
  }
  return parsed;
}

export function assertNoAmbientBetterAuthOverrides(environment: Environment): void {
  const unsupported = unsupportedBetterAuthEnvironmentNames.find(
    (name) => environment[name] !== undefined,
  );
  if (unsupported !== undefined) {
    throw new AuthConfigurationError(
      `${unsupported} is unsupported by ThesisTrace's exact Auth configuration`,
    );
  }
}

export function readAuthInitializerSettings(
  environment: Environment = process.env,
): AuthInitializerSettings {
  return {
    databaseUrl: parseDatabaseUrl(
      required(environment, "THESISTRACE_OWNER_DATABASE_URL"),
      "THESISTRACE_OWNER_DATABASE_URL",
      "thesistrace_owner",
    ),
  };
}

function required(environment: Environment, name: string): string {
  const value = environment[name];
  if (value === undefined || value.length === 0) {
    throw new AuthConfigurationError(`${name} is required`);
  }
  return value;
}

function parsePublicOrigin(
  value: string,
  environment: AuthSettings["environment"],
): string {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new AuthConfigurationError(
      "THESISTRACE_PUBLIC_ORIGIN must be an absolute HTTP origin",
    );
  }
  if (
    (url.protocol !== "http:" && url.protocol !== "https:") ||
    value !== url.origin ||
    url.username.length > 0 ||
    url.password.length > 0
  ) {
    throw new AuthConfigurationError(
      "THESISTRACE_PUBLIC_ORIGIN must contain only one canonical origin",
    );
  }

  const hostname = unbracketedHostname(url.hostname);
  const loopback = isLoopbackHostname(hostname);
  if (environment === "production") {
    if (url.protocol !== "https:" || loopback || isIP(hostname) !== 0) {
      throw new AuthConfigurationError(
        "THESISTRACE_PUBLIC_ORIGIN must use HTTPS and a non-loopback hostname in Production",
      );
    }
  } else if (url.protocol !== "http:" || !loopback) {
    throw new AuthConfigurationError(
      "THESISTRACE_PUBLIC_ORIGIN must use an HTTP loopback origin outside Production",
    );
  }
  return url.origin;
}

function parseDatabaseUrl(
  value: string,
  variableName: string,
  expectedUsername: string,
): string {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new AuthConfigurationError(`${variableName} must be a PostgreSQL URL`);
  }
  if (
    (url.protocol !== "postgresql:" && url.protocol !== "postgres:") ||
    url.hostname.length === 0 ||
    url.username.length === 0 ||
    url.password.length === 0 ||
    url.pathname === "/"
  ) {
    throw new AuthConfigurationError(
      `${variableName} must include PostgreSQL credentials, host, and database`,
    );
  }
  let username: string;
  try {
    username = decodeURIComponent(url.username);
    decodeURIComponent(url.password);
    decodeURIComponent(url.pathname.slice(1));
  } catch {
    throw new AuthConfigurationError(
      `${variableName} must use valid percent-encoding`,
    );
  }
  if (username !== expectedUsername) {
    throw new AuthConfigurationError(
      `${variableName} must use the ${expectedUsername} role`,
    );
  }
  return value;
}

function parseSecret(value: string, environment: AuthSettings["environment"]): string {
  if (value.length < 32) {
    throw new AuthConfigurationError(
      "BETTER_AUTH_SECRET must contain at least 32 characters",
    );
  }
  if (environment === "production") {
    if (!/^[0-9a-f]{64}$/.test(value) || isPredictableSecret(value)) {
      throw new AuthConfigurationError(
        "BETTER_AUTH_SECRET must encode 32 random bytes as lowercase hexadecimal in Production",
      );
    }
  }
  return value;
}

function isPredictableSecret(value: string): boolean {
  const bytes = [...Buffer.from(value, "hex")];
  if (new Set(bytes).size < 16) {
    return true;
  }
  for (let period = 1; period <= bytes.length / 2; period += 1) {
    if (
      bytes.length % period === 0 &&
      bytes.every((byte, index) => byte === bytes[index % period])
    ) {
      return true;
    }
  }
  const step = (bytes[1] ?? 0) - (bytes[0] ?? 0);
  return (
    (step === 1 || step === -1) &&
    bytes.slice(1).every((byte, index) => byte - (bytes[index] ?? 0) === step)
  );
}

function unbracketedHostname(hostname: string): string {
  return hostname.startsWith("[") && hostname.endsWith("]")
    ? hostname.slice(1, -1)
    : hostname;
}

function isLoopbackHostname(hostname: string): boolean {
  const normalized = hostname.toLowerCase().replace(/\.$/, "");
  if (normalized === "localhost" || normalized.endsWith(".localhost")) {
    return true;
  }
  if (isIP(hostname) === 4) {
    return hostname.startsWith("127.");
  }
  return normalized === "::1";
}

function parsePort(value: string): number {
  const port = Number(value);
  if (!Number.isInteger(port) || port < 1 || port > 65_535) {
    throw new AuthConfigurationError(
      "THESISTRACE_AUTH_PORT must be an integer from 1 through 65535",
    );
  }
  return port;
}

function parseResendApiKey(value: string): string {
  if (value.length > 512 || /\s/.test(value)) {
    throw new AuthConfigurationError(
      "RESEND_API_KEY must be one non-whitespace credential",
    );
  }
  return value;
}

function parseResendFromEmail(value: string): string {
  if (value !== value.trim() || value.length > 320 || /[\r\n]/.test(value)) {
    throw new AuthConfigurationError("RESEND_FROM_EMAIL must be one sender address");
  }
  const bracketed = /^[^<>]{1,100} <([^<>]+)>$/.exec(value);
  const address = bracketed?.[1] ?? value;
  if (!z.email().safeParse(address).success) {
    throw new AuthConfigurationError("RESEND_FROM_EMAIL must be one sender address");
  }
  return value;
}

function parseResendApiUrl(
  value: string,
  environment: AuthSettings["environment"],
): string {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new AuthConfigurationError(
      "THESISTRACE_RESEND_API_URL must be one canonical origin",
    );
  }
  if (value !== url.origin || url.username.length > 0 || url.password.length > 0) {
    throw new AuthConfigurationError(
      "THESISTRACE_RESEND_API_URL must be one canonical origin",
    );
  }
  if (environment === "production") {
    if (value !== "https://api.resend.com") {
      throw new AuthConfigurationError(
        "THESISTRACE_RESEND_API_URL must be https://api.resend.com in Production",
      );
    }
    return value;
  }
  const loopbackHttp =
    url.protocol === "http:" && isLoopbackHostname(unbracketedHostname(url.hostname));
  const composeTestFake = value === "http://resend-fake:8300";
  if (
    environment === "test"
      ? !loopbackHttp && !composeTestFake
      : !loopbackHttp && value !== "https://api.resend.com"
  ) {
    throw new AuthConfigurationError(
      "THESISTRACE_RESEND_API_URL must use the Test fake or Resend production origin",
    );
  }
  return value;
}
