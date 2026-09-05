import { createHash, randomBytes } from "node:crypto";
import { Hono } from "hono";
import { Pool } from "pg";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { createThesisTraceAuth, createClosedAuthLifecycle } from "./auth.js";
import { authTestSettings } from "../test-fixtures/auth-settings.js";
import { initializeAuthSchema } from "./schema-initialize.js";
import { ResearcherAccessService } from "./access.js";
import { enforceAuthSecretContract } from "./secret-contract.js";
import { AuthOperationCoordinator, CredentialOperationCoordinator } from "./coordination.js";
import { createAuthPool, createAuthCoordinationPool } from "./database.js";
import { createMcpConnectionsApp } from "./mcp-connections.js";
import { InvitationAdmission } from "./invitation-admission.js";

const url = process.env.THESISTRACE_AUTH_TEST_OWNER_DATABASE_URL;
if (!url) throw Error("isolated Auth test database required");
const owner = new Pool({ connectionString: url });
const runtimeUrl = new URL(url); runtimeUrl.username = "auth_runtime"; runtimeUrl.password = "auth-test-password";
const pool = createAuthPool(runtimeUrl.toString());
const coordinationPool = createAuthCoordinationPool(runtimeUrl.toString());
const coordination = new AuthOperationCoordinator(coordinationPool);
const settings = authTestSettings({ databaseUrl: runtimeUrl.toString() });
const admission = new InvitationAdmission();
let auth: ReturnType<typeof createThesisTraceAuth>;
let app: Hono;

beforeAll(async () => {
  await owner.query("DROP SCHEMA IF EXISTS auth CASCADE");
  await initializeAuthSchema(owner);
});
beforeEach(async () => {
  await owner.query('TRUNCATE auth."oauthClient", auth."user", auth."verification", auth."rateLimit" CASCADE');
  auth = createThesisTraceAuth(settings, pool, { ...createClosedAuthLifecycle(), invitationAdmission: admission,
    isResearcherActive: async id => (await pool.query('SELECT active FROM auth."user" WHERE id = $1', [id])).rows[0]?.active === true });
  app = new Hono().route("/", createMcpConnectionsApp(auth, pool, settings, coordination));
  app.all("/api/auth/*", c => auth.handler(c.req.raw));
  await auth.$context;
});
afterAll(async () => { await pool.end(); await coordinationPool.end(); await owner.end(); });
function request(path: string, body?: Record<string, unknown>, cookie?: string) {
  return app.request(`${settings.publicOrigin}${path}`, { method: body ? "POST" : "GET",
    headers: { origin: settings.publicOrigin, ...(body ? { "content-type": "application/json" } : {}), ...(cookie ? { cookie } : {}) },
    ...(body ? { body: JSON.stringify(body) } : {}) });
}
async function signIn(email: string) {
  const response = await admission.run(email, () => auth.handler(new Request(`${settings.publicOrigin}/api/auth/sign-up/email`, {
    method: "POST", headers: { origin: settings.publicOrigin, "content-type": "application/json", "x-thesistrace-client-ip": email.includes("other") ? "192.0.2.2" : "192.0.2.1" },
    body: JSON.stringify({ email, name: "Researcher", password: "correct-horse-battery-staple" }),
  })));
  expect(response.status).toBe(200);
  return response.headers.getSetCookie().map(value => value.split(";")[0]).join("; ");
}
async function registeredClient() {
  const response = await request("/api/auth/oauth2/register", { client_name: "Codex", application_type: "native",
    token_endpoint_auth_method: "none", redirect_uris: ["http://127.0.0.1:8765/callback"],
    grant_types: ["authorization_code", "refresh_token"], response_types: ["code"] });
  expect(response.status, await response.clone().text()).toBe(201);
  return await response.json() as { client_id: string };
}
async function authorization(cookie: string, clientId: string) {
  const verifier = randomBytes(32).toString("base64url");
  const query = new URLSearchParams({ client_id: clientId, redirect_uri: "http://127.0.0.1:8765/callback",
    response_type: "code", scope: "research:read research:execute tracking:read tracking:execute offline_access",
    resource: settings.mcpAudience, state: "test-state", code_challenge_method: "S256",
    code_challenge: createHash("sha256").update(verifier).digest("base64url"), prompt: "consent" });
  const response = await request(`/api/auth/oauth2/authorize?${query}`, undefined, cookie);
  expect(response.status, await response.clone().text()).toBe(302);
  const consent = new URL(response.headers.get("location")!, settings.publicOrigin);
  expect(consent.pathname).toBe("/connections/mcp/authorize");
  return { verifier, oauth_query: consent.search.slice(1) };
}
async function token(body: Record<string, string>) {
  return app.request(`${settings.publicOrigin}/api/auth/oauth2/token`, { method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams(body).toString() });
}
async function connected(cookie: string, clientId: string) {
  const flow = await authorization(cookie, clientId);
  const view = await request("/api/auth/mcp/authorization", { oauth_query: flow.oauth_query }, cookie);
  expect(view.status, await view.clone().text()).toBe(200);
  expect(await view.json()).toMatchObject({ name: "Codex", scopes: expect.arrayContaining(["research:read"]) });
  const response = await request("/api/auth/oauth2/consent", { accept: true, oauth_query: flow.oauth_query }, cookie);
  expect(response.status, await response.clone().text()).toBe(200);
  const consent = await response.json() as { url: string };
  const callback = new URL(consent.url);
  expect(callback.searchParams.get("state")).toBe("test-state");
  const issued = await token({ grant_type: "authorization_code", client_id: clientId, code: callback.searchParams.get("code")!,
    code_verifier: flow.verifier, redirect_uri: "http://127.0.0.1:8765/callback", resource: settings.mcpAudience });
  expect(issued.status, issued.status === 200 ? "" : await issued.clone().text()).toBe(200);
  return await issued.json() as { access_token: string; refresh_token: string };
}
async function verify(accessToken: string) { return (await request("/internal/mcp/verify", { token: accessToken })).json(); }

describe.sequential("External MCP OAuth", () => {
  it("discovers, authorizes with PKCE, lists only owned apps and revokes access and refresh tokens", async () => {
    const metadata = await request("/.well-known/oauth-authorization-server/api/auth");
    expect(metadata.status).toBe(200);
    expect(await metadata.json()).toMatchObject({ issuer: `${settings.publicOrigin}/api/auth`, code_challenge_methods_supported: ["S256"] });
    const cookie = await signIn("mcp-owner@example.com");
    const other = await signIn("mcp-other@example.com");
    const client = await registeredClient();
    const issued = await connected(cookie, client.client_id);
    expect(await verify(issued.access_token)).toMatchObject({ active: true, client_id: client.client_id, resource: settings.mcpAudience });
    expect(await (await request("/api/auth/mcp/connections", undefined, other)).json()).toMatchObject({ apps: [] });
    const list = await (await request("/api/auth/mcp/connections", undefined, cookie)).json() as { apps: { id: string }[] };
    expect(list.apps).toHaveLength(1);
    expect((await request("/api/auth/mcp/revoke", { id: list.apps[0]!.id }, other)).status).toBe(404);
    expect(await verify(issued.access_token)).toMatchObject({ active: true });
    const refreshed = await token({ grant_type: "refresh_token", client_id: client.client_id, refresh_token: issued.refresh_token, resource: settings.mcpAudience });
    expect(refreshed.status).toBe(200);
    const rotated = await refreshed.json() as { access_token: string; refresh_token: string };
    expect(await verify(rotated.access_token)).toMatchObject({ active: true });
    const pending = await authorization(cookie, client.client_id);
    const pendingConsent = await request("/api/auth/oauth2/consent", { accept: true, oauth_query: pending.oauth_query }, cookie);
    const pendingCallback = new URL((await pendingConsent.json() as { url: string }).url);
    expect((await request("/api/auth/mcp/revoke", { id: list.apps[0]!.id }, cookie)).status).toBe(204);
    expect(await verify(issued.access_token)).toEqual({ active: false });
    expect(await verify(rotated.access_token)).toEqual({ active: false });
    expect((await token({ grant_type: "refresh_token", client_id: client.client_id, refresh_token: rotated.refresh_token, resource: settings.mcpAudience })).status).toBe(400);
    expect((await token({ grant_type: "authorization_code", client_id: client.client_id, code: pendingCallback.searchParams.get("code")!, code_verifier: pending.verifier, redirect_uri: "http://127.0.0.1:8765/callback", resource: settings.mcpAudience })).status).toBe(400);
    expect((await token({ grant_type: "refresh_token", client_id: client.client_id, refresh_token: issued.refresh_token, resource: settings.mcpAudience })).status).toBe(400);
    const reauthorized = await connected(cookie, client.client_id);
    expect(await verify(reauthorized.access_token)).toMatchObject({ active: true });
    expect(await verify(issued.access_token)).toEqual({ active: false });
  });
  it("does not restore external credentials after account reactivation or secret rotation", async () => {
    const cookie = await signIn("mcp-lifecycle@example.com");
    const client = await registeredClient();
    const issued = await connected(cookie, client.client_id);
    const service = new ResearcherAccessService({ authSecret: settings.secret, pool,
      credentialCoordinator: new CredentialOperationCoordinator({ authSecret: settings.secret, pool, coordination }) });
    const id = await service.resolveResearcherId({ email: "mcp-lifecycle@example.com" });
    await service.deactivate(id);
    await service.reactivate(id);
    expect(await verify(issued.access_token)).toEqual({ active: false });
    expect((await token({ grant_type: "refresh_token", client_id: client.client_id, refresh_token: issued.refresh_token, resource: settings.mcpAudience })).status).toBe(400);
    const nextCookie = await signIn("mcp-other-rotation@example.com");
    const next = await connected(nextCookie, client.client_id);
    await enforceAuthSecretContract(pool, settings.secret);
    await enforceAuthSecretContract(pool, `${settings.secret}-rotated`);
    expect(await verify(next.access_token)).toEqual({ active: false });
    expect((await token({ grant_type: "refresh_token", client_id: client.client_id, refresh_token: next.refresh_token, resource: settings.mcpAudience })).status).toBe(400);
  });
  it("rejects tampered consent, missing PKCE, foreign origins and inactive owners", async () => {
    const cookie = await signIn("mcp-security@example.com");
    const client = await registeredClient();
    const flow = await authorization(cookie, client.client_id);
    const forged = flow.oauth_query.replace("research%3Aread", "research%3Acancel");
    expect((await request("/api/auth/mcp/authorization", { oauth_query: forged }, cookie)).status).toBe(400);
    expect((await request("/api/auth/oauth2/consent", { accept: true, oauth_query: forged }, cookie)).status).toBe(400);
    const noPkce = await request(`/api/auth/oauth2/authorize?${new URLSearchParams({ client_id: client.client_id, redirect_uri: "http://127.0.0.1:8765/callback", response_type: "code", scope: "research:read", resource: settings.mcpAudience })}`, undefined, cookie);
    expect(noPkce.status === 400 || noPkce.headers.get("location")?.includes("error=")).toBe(true);
    expect((await app.request(`${settings.publicOrigin}/api/auth/mcp/revoke`, { method: "POST", headers: { cookie, origin: "https://evil.test", "content-type": "application/json" }, body: JSON.stringify({ id: "00000000-0000-4000-8000-000000000000" }) })).status).toBe(403);
    const issued = await connected(cookie, client.client_id);
    await owner.query('UPDATE auth."user" SET active = false WHERE email = $1', ["mcp-security@example.com"]);
    expect(await verify(issued.access_token)).toEqual({ active: false });
    expect((await request("/api/auth/mcp/connections", undefined, cookie)).status).toBe(401);
  });
});
