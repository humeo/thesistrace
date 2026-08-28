import { isIP } from "node:net";

import { z } from "zod";

import { AuthConfigurationError } from "./failure.js";

const runtimeEnvironmentSchema = z.enum(["development", "test", "production"]);

export type AuthSettings = Readonly<{
  databaseUrl: string;
  environment: z.infer<typeof runtimeEnvironmentSchema>;
  host: string;
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
    port,
    publicOrigin,
    resendApiKey,
    resendApiUrl,
    resendFromEmail,
    secret,
    secureCookies: parsedEnvironment.data === "production",
  };
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
