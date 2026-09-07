import { Hono } from "hono";
import type { AuthOperationCoordinator } from "./coordination.js";
import { bodyLimit } from "hono/body-limit";
import type { Pool } from "pg";
import { z } from "zod";
import type { ThesisTraceAuth } from "./auth.js";
import type { AuthSettings } from "./config.js";
import { MCP_ACCESS_PREFIX, mcpTokenHash } from "./mcp-oauth.js";

// The resource server is the only caller of /internal/mcp/verify. Caddy never
// exposes /internal. Bearer values are never returned, persisted in plaintext,
// or accepted from browser query parameters.
export function createMcpConnectionsApp(auth: ThesisTraceAuth, pool: Pool, settings: AuthSettings, coordination: AuthOperationCoordinator) {
  const app = new Hono<{ Variables: { mcpResearcher: string } }>();
  app.use("*", async (c, next) => { c.header("Cache-Control", "no-store"); await next(); });
  app.use("/api/auth/*", bodyLimit({ maxSize: 32768 }));
  // Serialize issuance and revocation for the same OAuth client across Auth
  // processes. The existing coordination pool avoids holding runtime pool
  // connections while the provider performs its own database operations.
  app.use("/api/auth/*", async (c, next) => {
    if (!["/api/auth/oauth2/authorize", "/api/auth/oauth2/consent", "/api/auth/oauth2/token", "/api/auth/sign-in/email"].includes(c.req.path)) return next();
    let values: Record<string, unknown> = Object.fromEntries(new URL(c.req.url).searchParams);
    if (c.req.method === "POST") {
      try {
        values = c.req.header("content-type")?.startsWith("application/x-www-form-urlencoded")
          ? Object.fromEntries(new URLSearchParams(await c.req.raw.clone().text()))
          : await c.req.raw.clone().json();
      } catch { return c.json({ code: "INVALID_REQUEST" }, 400); }
    }
    if (!values || typeof values !== "object" || Array.isArray(values)) return c.json({ code: "INVALID_REQUEST" }, 400);
    const oauthQuery = typeof values.oauth_query === "string" ? new URLSearchParams(values.oauth_query) : null;
    let clientId = oauthQuery?.get("client_id") || values.client_id;
    if (c.req.path === "/api/auth/oauth2/token") {
      // Derive the lock from the stored grant, not caller-supplied client
      // credentials; Basic and body credentials must not choose different locks.
      if (values.grant_type === "authorization_code" && typeof values.code === "string") {
        const stored = await pool.query(`SELECT
          (CASE WHEN value IS JSON OBJECT THEN value::jsonb ELSE '{}'::jsonb END)->'query'->>'client_id' AS client_id
          FROM auth."verification" WHERE identifier = $1`, [mcpTokenHash(values.code)]);
        clientId = stored.rows[0]?.client_id;
      } else if (values.grant_type === "refresh_token" && typeof values.refresh_token === "string"
        && values.refresh_token.startsWith("tt_refresh_")) {
        const stored = await pool.query('SELECT "clientId" FROM auth."oauthRefreshToken" WHERE token = $1',
          [mcpTokenHash(values.refresh_token.slice("tt_refresh_".length))]);
        clientId = stored.rows[0]?.clientId;
      }
    }
    if (typeof clientId !== "string" || !clientId || clientId.length > 2048) return next();
    return coordination.run([`mcp-oauth-client:${clientId}`], () => next());
  });
  app.get("/.well-known/oauth-authorization-server/api/auth", async (c) =>
    c.json(await auth.api.getOAuthServerConfig()));
  app.get("/api/auth/.well-known/oauth-authorization-server", async (c) =>
    c.json(await auth.api.getOAuthServerConfig()));
  app.post("/internal/mcp/verify", async (c) => {
    const parsed = z.object({ token: z.string().min(1).max(4096) }).strict().safeParse(await c.req.json());
    if (!parsed.success || !parsed.data.token.startsWith(MCP_ACCESS_PREFIX)) return c.json({ active: false });
    const result = await pool.query<{
      id: string; clientId: string; userId: string; scopes: string[]; expiresAt: Date;
    }>(`
      SELECT t.id, t."clientId", t."userId", t.scopes, t."expiresAt"
      FROM auth."oauthAccessToken" t
      JOIN auth."user" u ON u.id = t."userId" AND u.active
      JOIN auth."oauthClient" cl ON cl."clientId" = t."clientId" AND cl.disabled IS NOT TRUE
      JOIN auth."oauthResource" r ON r.identifier = $2 AND r.disabled IS NOT TRUE
      WHERE t.token = $1 AND t."expiresAt" > CURRENT_TIMESTAMP AND t.revoked IS NULL
        AND t.resources @> jsonb_build_array($2::text)
        AND t.confirmation IS NULL
        AND (t."sessionId" IS NULL OR EXISTS (
          SELECT 1 FROM auth."session" s WHERE s.id = t."sessionId" AND s."expiresAt" > CURRENT_TIMESTAMP))
        AND EXISTS (SELECT 1 FROM auth."oauthConsent" g
          WHERE g."clientId" = t."clientId" AND g."userId" = t."userId"
            AND g."createdAt" <= t."createdAt" AND g.scopes @> t.scopes
            AND g.resources @> jsonb_build_array($2::text))
    `, [mcpTokenHash(parsed.data.token.slice(MCP_ACCESS_PREFIX.length)), settings.mcpAudience]);
    const token = result.rows[0];
    if (!token) return c.json({ active: false });
    const scopes = token.scopes.filter((scope) => (settings.mcpGrantScopes as readonly string[]).includes(scope));
    if (!scopes.length) return c.json({ active: false });
    return c.json({ active: true, sub: token.userId, client_id: token.clientId,
      scopes, exp: Math.floor(token.expiresAt.getTime() / 1000), jti: token.id,
      resource: settings.mcpAudience });
  });
  app.use("/api/auth/mcp/*", async (c, next) => {
    c.header("Cache-Control", "no-store");
    if ((c.req.header("sec-fetch-site") && c.req.header("sec-fetch-site") !== "same-origin")
      || (c.req.method !== "GET" && c.req.header("origin") !== settings.publicOrigin)) {
      return c.json({ code: "ORIGIN_NOT_ALLOWED" }, 403);
    }
    const session = await auth.api.getSession({ headers: c.req.raw.headers,
      query: { disableCookieCache: true, disableRefresh: true } });
    if (!session?.user.active) return c.json({ code: "AUTHENTICATION_REQUIRED" }, 401);
    // Store only the verified owner on the request context.
    c.set("mcpResearcher", session.user.id);
    await next();
  });
  app.post("/api/auth/mcp/authorization", async (c) => {
    const input = z.object({ oauth_query: z.string().max(16384) }).strict().safeParse(await c.req.json());
    if (!input.success) return c.json({ code: "INVALID_REQUEST" }, 400);
    try {
      const query = new URLSearchParams(input.data.oauth_query);
      const client = await auth.api.getOAuthClientPublicPrelogin({ body: { ...input.data, client_id: query.get("client_id") || "" }, headers: c.req.raw.headers });
      return c.json({ name: client.client_name || client.client_id, scopes: (query.get("scope") || "").split(" ").filter(Boolean) });
    } catch { return c.json({ code: "AUTHORIZATION_REQUEST_INVALID" }, 400); }
  });
  app.get("/api/auth/mcp/connections", async (c) => {
    const result = await pool.query(`
      SELECT g.id, cl.name, g."clientId" AS client_id, g.scopes,
        g."createdAt" AS authorized_at
      FROM auth."oauthConsent" g JOIN auth."oauthClient" cl ON cl."clientId" = g."clientId"
      WHERE g."userId" = $1 AND g.resources @> jsonb_build_array($2::text)
      ORDER BY g."createdAt" DESC, g.id
    `, [c.get("mcpResearcher"), settings.mcpAudience]);
    return c.json({ server_url: settings.mcpAudience, apps: result.rows });
  });
  app.post("/api/auth/mcp/revoke", async (c) => {
    if (!c.req.header("content-type")?.startsWith("application/json")) return c.json({ code: "INVALID_REQUEST" }, 415);
    const input = z.object({ id: z.uuid() }).strict().safeParse(await c.req.json());
    if (!input.success) return c.json({ code: "INVALID_REQUEST" }, 400);
    const selected = await pool.query('SELECT "clientId" FROM auth."oauthConsent" WHERE id = $1 AND "userId" = $2', [input.data.id, c.get("mcpResearcher")]);
    if (!selected.rows.length) return c.json({ code: "NOT_FOUND" }, 404);
    return coordination.run([`mcp-oauth-client:${selected.rows[0].clientId}`], async () => {
    const db = await pool.connect();
    try {
      await db.query("BEGIN");
      const grants = await db.query(`SELECT "clientId" FROM auth."oauthConsent"
        WHERE id = $1 AND "userId" = $2 FOR UPDATE`, [input.data.id, c.get("mcpResearcher")]);
      if (!grants.rows.length) { await db.query("ROLLBACK"); return c.json({ code: "NOT_FOUND" }, 404); }
      const values = [grants.rows[0].clientId, c.get("mcpResearcher")];
      await db.query(`DELETE FROM auth."verification" WHERE
        CASE WHEN value IS JSON OBJECT THEN value::jsonb ELSE '{}'::jsonb END
          @> jsonb_build_object('type', 'authorization_code', 'userId', $2::text, 'query', jsonb_build_object('client_id', $1::text))`, values);
      await db.query('DELETE FROM auth."oauthAccessToken" WHERE "clientId" = $1 AND "userId" = $2', values);
      await db.query('DELETE FROM auth."oauthRefreshToken" WHERE "clientId" = $1 AND "userId" = $2', values);
      await db.query('DELETE FROM auth."oauthConsent" WHERE "clientId" = $1 AND "userId" = $2', values);
      await db.query("COMMIT");
      return c.body(null, 204);
    } catch (error) { await db.query("ROLLBACK"); throw error; }
    finally { db.release(); }
    });
  });
  return app;
}
