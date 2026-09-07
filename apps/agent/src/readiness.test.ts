import type { Pool } from "pg";
import { describe, expect, it, vi } from "vitest";

import type { AgentSettings } from "./config.js";
import { createAgentReadiness } from "./readiness.js";

const settings = {
  authInternalOrigin: "http://auth:8200",
  mcpInternalUrl: "http://api:8100/mcp",
} as AgentSettings;

describe("Agent dependency readiness", () => {
  it("requires the database, Auth readiness, and canonical MCP metadata", async () => {
    const pool = readyPool();
    const fetcher = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = new URL(input instanceof Request ? input.url : input);
      expect(init).toMatchObject({
        cache: "no-store",
        credentials: "omit",
        method: "GET",
        redirect: "error",
      });
      expect(new Headers(init?.headers)).toEqual(
        new Headers({ Accept: "application/json" }),
      );
      expect(init?.signal).toBeInstanceOf(AbortSignal);
      if (url.pathname === "/health/ready") {
        expect(url.toString()).toBe("http://auth:8200/health/ready");
        return Response.json({ status: "ready" });
      }
      expect(url.toString()).toBe(
        "http://api:8100/.well-known/oauth-protected-resource/mcp",
      );
      return Response.json({
        authorization_servers: ["https://research.thesistrace.test/api/auth"],
        resource: "https://research.thesistrace.test/mcp",
      });
    });
    const ready = createAgentReadiness(settings, pool, { fetch: fetcher });

    await expect(ready()).resolves.toBe(true);
    expect(pool.query).toHaveBeenCalledWith("SELECT 1 AS ready");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it.each([
    ["Auth unavailable", "/health/ready", Response.json(
      { status: "unavailable" },
      { status: 503 },
    )],
    ["Auth malformed", "/health/ready", Response.json({ status: "ok" })],
    ["MCP metadata unavailable", "/.well-known/oauth-protected-resource/mcp",
      Response.json({ code: "UNAVAILABLE" }, { status: 503 })],
    ["MCP metadata malformed", "/.well-known/oauth-protected-resource/mcp",
      Response.json({
        authorization_servers: [],
        resource: "http://research.thesistrace.test/mcp",
      })],
  ])("fails closed when %s", async (_name, failedPath, failedResponse) => {
    const ready = createAgentReadiness(settings, readyPool(), {
      fetch: async (input) => {
        const url = new URL(input instanceof Request ? input.url : input);
        if (url.pathname === failedPath) return failedResponse.clone();
        if (url.pathname === "/health/ready") {
          return Response.json({ status: "ready" });
        }
        return Response.json({
          authorization_servers: ["https://research.thesistrace.test/api/auth"],
          resource: "https://research.thesistrace.test/mcp",
        });
      },
    });

    await expect(ready()).resolves.toBe(false);
  });

  it("fails closed when the database is unavailable", async () => {
    const pool = {
      query: vi.fn(async () => {
        throw new Error("private database failure");
      }),
    } as unknown as Pool;
    const ready = createAgentReadiness(settings, pool, {
      fetch: healthyFetch,
    });

    await expect(ready()).resolves.toBe(false);
  });

  it("bounds a database acquisition that never resolves", async () => {
    const pool = {
      query: vi.fn(async () => await new Promise<never>(() => undefined)),
    } as unknown as Pool;
    const ready = createAgentReadiness(settings, pool, {
      fetch: healthyFetch,
      timeoutMs: 5,
    });

    await expect(ready()).resolves.toBe(false);
    expect(pool.query).toHaveBeenCalledOnce();
  });

  it("bounds an unresponsive dependency and sends no credentials", async () => {
    const observedHeaders: Headers[] = [];
    const ready = createAgentReadiness(settings, readyPool(), {
      fetch: async (_input, init) => {
        observedHeaders.push(new Headers(init?.headers));
        return await new Promise<never>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new Error("aborted")), {
            once: true,
          });
        });
      },
      timeoutMs: 5,
    });

    await expect(ready()).resolves.toBe(false);
    expect(observedHeaders).toHaveLength(2);
    for (const headers of observedHeaders) {
      expect([...headers.keys()]).toEqual(["accept"]);
      expect(headers.get("authorization")).toBeNull();
      expect(headers.get("cookie")).toBeNull();
    }
  });

  it("rejects oversized readiness documents", async () => {
    const ready = createAgentReadiness(settings, readyPool(), {
      fetch: async (input) => {
        const url = new URL(input instanceof Request ? input.url : input);
        if (url.pathname === "/health/ready") {
          return new Response("x".repeat(16 * 1024 + 1), {
            headers: { "content-type": "application/json" },
          });
        }
        return healthyFetch(input);
      },
    });

    await expect(ready()).resolves.toBe(false);
  });
});

function readyPool(): Pool {
  return {
    query: vi.fn(async () => ({ rows: [{ ready: 1 }] })),
  } as unknown as Pool;
}

async function healthyFetch(input: string | URL | Request): Promise<Response> {
  const url = new URL(input instanceof Request ? input.url : input);
  if (url.pathname === "/health/ready") {
    return Response.json({ status: "ready" });
  }
  return Response.json({
    authorization_servers: ["https://research.thesistrace.test/api/auth"],
    resource: "https://research.thesistrace.test/mcp",
  });
}


it.each(["test", "development", "production"] as const)("only permits loopback HTTP metadata outside production (%s)", async environment => {
  const ready = createAgentReadiness({ ...settings, environment }, readyPool(), {
    fetch: async input => new URL(input instanceof Request ? input.url : input).pathname === "/health/ready"
      ? Response.json({ status: "ready" })
      : Response.json({ resource: "http://127.0.0.1:5173/mcp", authorization_servers: ["http://127.0.0.1:5173/api/auth"] }),
  });
  await expect(ready()).resolves.toBe(environment !== "production");
});
