import type { Pool } from "pg";

import type { AgentSettings } from "./config.js";

const DEPENDENCY_TIMEOUT_MS = 2_000;
const MAX_READINESS_DOCUMENT_BYTES = 16 * 1024;

type ReadinessDependencies = Readonly<{
  fetch?: typeof globalThis.fetch;
  timeoutMs?: number;
}>;

export function createAgentReadiness(
  settings: AgentSettings,
  pool: Pool,
  dependencies: ReadinessDependencies = {},
): () => Promise<boolean> {
  const fetcher = dependencies.fetch ?? globalThis.fetch;
  const timeoutMs = dependencies.timeoutMs ?? DEPENDENCY_TIMEOUT_MS;
  const authReadinessUrl = new URL("/health/ready", settings.authInternalOrigin);
  const mcpUrl = new URL(settings.mcpInternalUrl);
  const mcpMetadataUrl = new URL(
    "/.well-known/oauth-protected-resource/mcp",
    mcpUrl.origin,
  );

  return async () => {
    const [database, auth, mcpMetadata] = await Promise.all([
      databaseReady(pool, timeoutMs),
      probeJson(fetcher, authReadinessUrl, timeoutMs, isAuthReady),
      probeJson(fetcher, mcpMetadataUrl, timeoutMs, value => isMcpMetadata(value, settings.environment === "test" || settings.environment === "development")),
    ]);
    return database && auth && mcpMetadata;
  };
}

async function databaseReady(pool: Pool, timeoutMs: number): Promise<boolean> {
  let timeout: NodeJS.Timeout | undefined;
  try {
    const result = await Promise.race([
      // This dedicated readiness Pool has short acquisition/query timeouts.
      // The outer deadline also protects the HTTP handler from a stalled driver.
      pool.query<{ ready: number }>("SELECT 1 AS ready"),
      new Promise<never>((_resolve, reject) => {
        timeout = setTimeout(
          () => reject(new Error("DATABASE_READINESS_TIMEOUT")),
          timeoutMs,
        );
        timeout.unref();
      }),
    ]);
    return result.rows[0]?.ready === 1;
  } catch {
    return false;
  } finally {
    if (timeout !== undefined) clearTimeout(timeout);
  }
}

async function probeJson(
  fetcher: typeof globalThis.fetch,
  url: URL,
  timeoutMs: number,
  validate: (value: unknown) => boolean,
): Promise<boolean> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  timeout.unref();
  try {
    const response = await fetcher(url, {
      cache: "no-store",
      credentials: "omit",
      headers: { Accept: "application/json" },
      method: "GET",
      redirect: "error",
      signal: controller.signal,
    });
    if (
      response.status !== 200
      || !response.headers.get("content-type")?.toLowerCase().startsWith(
        "application/json",
      )
    ) {
      return false;
    }
    const document = await readBoundedJson(response);
    return document !== undefined && validate(document);
  } catch {
    return false;
  } finally {
    clearTimeout(timeout);
  }
}

async function readBoundedJson(response: Response): Promise<unknown | undefined> {
  const declaredLength = response.headers.get("content-length");
  if (
    declaredLength !== null
    && (!/^(0|[1-9][0-9]*)$/.test(declaredLength)
      || Number(declaredLength) > MAX_READINESS_DOCUMENT_BYTES)
  ) {
    return undefined;
  }
  if (response.body === null) return undefined;

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let bytes = 0;
  let text = "";
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      bytes += chunk.value.byteLength;
      if (bytes > MAX_READINESS_DOCUMENT_BYTES) {
        await reader.cancel();
        return undefined;
      }
      text += decoder.decode(chunk.value, { stream: true });
    }
    text += decoder.decode();
    return JSON.parse(text) as unknown;
  } catch {
    return undefined;
  }
}

function isAuthReady(value: unknown): boolean {
  return isRecord(value) && value.status === "ready";
}

function isMcpMetadata(value: unknown, allowLoopback: boolean): boolean {
  if (
    !isRecord(value)
    || !isCanonicalMcpResource(value.resource, allowLoopback)
    || !Array.isArray(value.authorization_servers)
    || value.authorization_servers.length === 0
    || !value.authorization_servers.every(url => isCanonicalUrl(url, allowLoopback))
  ) {
    return false;
  }
  return true;
}

function isCanonicalMcpResource(value: unknown, allowLoopback: boolean): boolean {
  if (!isCanonicalUrl(value, allowLoopback)) return false;
  return new URL(value).pathname === "/mcp";
}

function isCanonicalUrl(value: unknown, allowLoopback: boolean): value is string {
  if (typeof value !== "string") return false;
  try {
    const url = new URL(value);
    return (url.protocol === "https:" || (allowLoopback && url.protocol === "http:" && ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname)))
      && url.username.length === 0
      && url.password.length === 0
      && url.search.length === 0
      && url.hash.length === 0
      && value === url.toString();
  } catch {
    return false;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
