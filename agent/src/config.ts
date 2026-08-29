import { isIP } from "node:net";

import { z } from "zod";

import { AgentConfigurationError } from "./failure.js";
import { readModelRegistry, type ModelRegistry } from "./model-registry.js";

const runtimeEnvironmentSchema = z.enum(["development", "test", "production"]);

export type AgentSettings = Readonly<{
  agentBuildRevision: string;
  authInternalOrigin: string;
  databaseUrl: string;
  environment: z.infer<typeof runtimeEnvironmentSchema>;
  host: string;
  modelRegistry: ModelRegistry;
  port: number;
  publicOrigin: string;
}>;

export type AgentInitializerSettings = Readonly<{ databaseUrl: string }>;

type Environment = Readonly<Record<string, string | undefined>>;

export function readAgentSettings(
  environment: Environment = process.env,
): AgentSettings {
  const runtimeEnvironment = required(environment, "THESISTRACE_ENVIRONMENT");
  const parsedEnvironment = runtimeEnvironmentSchema.safeParse(runtimeEnvironment);
  if (!parsedEnvironment.success) throw new AgentConfigurationError();

  const publicOrigin = parsePublicOrigin(
    required(environment, "THESISTRACE_PUBLIC_ORIGIN"),
    parsedEnvironment.data,
  );
  const authInternalOrigin = parseInternalOrigin(
    required(environment, "THESISTRACE_AUTH_INTERNAL_ORIGIN"),
  );
  const databaseUrl = parseDatabaseUrl(
    required(environment, "THESISTRACE_AGENT_DATABASE_URL"),
    "agent_runtime",
  );
  const agentBuildRevision = parseBuildRevision(
    required(environment, "THESISTRACE_AGENT_BUILD_REVISION"),
  );
  const modelRegistry = readModelRegistry(
    required(environment, "THESISTRACE_AGENT_MODEL_REGISTRY"),
    environment,
  );

  return {
    agentBuildRevision,
    authInternalOrigin,
    databaseUrl,
    environment: parsedEnvironment.data,
    host: environment.THESISTRACE_AGENT_HOST ?? "0.0.0.0",
    modelRegistry,
    port: parsePort(environment.THESISTRACE_AGENT_PORT ?? "8400"),
    publicOrigin,
  };
}

export function readAgentInitializerSettings(
  environment: Environment = process.env,
): AgentInitializerSettings {
  return {
    databaseUrl: parseDatabaseUrl(
      required(environment, "THESISTRACE_OWNER_DATABASE_URL"),
      "thesistrace_owner",
    ),
  };
}

function required(environment: Environment, name: string): string {
  const value = environment[name];
  if (value === undefined || value.length === 0) throw new AgentConfigurationError();
  return value;
}

function parsePublicOrigin(
  value: string,
  environment: AgentSettings["environment"],
): string {
  const url = parseExactOrigin(value);
  const hostname = unbracketedHostname(url.hostname);
  const loopback = isLoopbackHostname(hostname);
  if (environment === "production") {
    if (url.protocol !== "https:" || loopback || isIP(hostname) !== 0) {
      throw new AgentConfigurationError();
    }
  } else if (url.protocol !== "http:" || !loopback) {
    throw new AgentConfigurationError();
  }
  return url.origin;
}

function parseInternalOrigin(value: string): string {
  const url = parseExactOrigin(value);
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new AgentConfigurationError();
  }
  return url.origin;
}

function parseExactOrigin(value: string): URL {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new AgentConfigurationError();
  }
  if (
    value !== url.origin
    || url.username.length > 0
    || url.password.length > 0
    || (url.protocol !== "http:" && url.protocol !== "https:")
  ) {
    throw new AgentConfigurationError();
  }
  return url;
}

function parsePort(value: string): number {
  if (!/^[0-9]+$/.test(value)) throw new AgentConfigurationError();
  const port = Number(value);
  if (!Number.isSafeInteger(port) || port < 1 || port > 65_535) {
    throw new AgentConfigurationError();
  }
  return port;
}

function parseDatabaseUrl(value: string, expectedUsername: string): string {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new AgentConfigurationError();
  }
  if (
    (url.protocol !== "postgresql:" && url.protocol !== "postgres:")
    || url.hostname.length === 0
    || url.username.length === 0
    || url.password.length === 0
    || url.pathname === "/"
  ) {
    throw new AgentConfigurationError();
  }
  try {
    if (decodeURIComponent(url.username) !== expectedUsername) {
      throw new AgentConfigurationError();
    }
    decodeURIComponent(url.password);
    decodeURIComponent(url.pathname.slice(1));
  } catch (error) {
    if (error instanceof AgentConfigurationError) throw error;
    throw new AgentConfigurationError();
  }
  return value;
}

function parseBuildRevision(value: string): string {
  if (
    value !== value.trim()
    || value.length < 1
    || value.length > 128
    || /[\p{Cc}\p{Cf}\p{Cs}\p{Zl}\p{Zp}]/u.test(value)
  ) {
    throw new AgentConfigurationError();
  }
  return value;
}

function unbracketedHostname(hostname: string): string {
  return hostname.startsWith("[") && hostname.endsWith("]")
    ? hostname.slice(1, -1)
    : hostname;
}

function isLoopbackHostname(hostname: string): boolean {
  const normalized = hostname.toLowerCase().replace(/\.$/, "");
  if (normalized === "localhost" || normalized.endsWith(".localhost")) return true;
  if (isIP(hostname) === 4) return hostname.startsWith("127.");
  return normalized === "::1" || normalized === "::ffff:7f00:1";
}
