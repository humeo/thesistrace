import { createHash, randomBytes } from "node:crypto";
import { createServer } from "node:http";
import { request as apiRequest } from "@playwright/test";
import { test, expect, emailCode } from "./auth-fixture";

// Authentication acceptance intentionally exercises the OAuth protocol directly.
// The MCP page's setup controls have separate product/browser coverage.
test("External OAuth authentication completes login, consent, token refresh and revocation", async ({page, researcher}) => {
  const base = process.env.THESISTRACE_TEST_WEB_ORIGIN!;
  let receive: (url: URL) => void = () => undefined;
  const received = new Promise<URL>(resolve => { receive = resolve; });
  const callback = createServer((request, response) => {
    receive(new URL(request.url!, "http://127.0.0.1"));
    response.writeHead(200, { "content-type": "text/html", "cache-control": "no-store" });
    response.end("<p>Authorization complete. Return to QAgentis.</p>");
  });
  await new Promise<void>(resolve => callback.listen(0, "127.0.0.1", resolve));
  const external = await apiRequest.newContext({ baseURL: base });
  try {
    const address = callback.address();
    if (!address || typeof address === "string") throw Error("callback not listening");
    const redirect = `http://127.0.0.1:${address.port}/callback`;
    const registration = await external.post("/api/auth/oauth2/register", { data: {
      client_name: "OAuth acceptance client", application_type: "native", token_endpoint_auth_method: "none",
      redirect_uris: [redirect], grant_types: ["authorization_code", "refresh_token"], response_types: ["code"],
    } });
    expect(registration.status()).toBe(201);
    const client = await registration.json() as { client_id: string };
    const verifier = randomBytes(32).toString("base64url");
    const query = new URLSearchParams({ client_id: client.client_id, response_type: "code", redirect_uri: redirect,
      scope: "research:read tracking:read offline_access", resource: `${base}/mcp`, state: "oauth-acceptance",
      code_challenge_method: "S256", code_challenge: createHash("sha256").update(verifier).digest("base64url") });
    await page.context().clearCookies();
    await page.goto(`/api/auth/oauth2/authorize?${query}`);
    await expect(page.getByRole("heading", { name: "Welcome to QAgentis" })).toBeVisible();
    await page.getByLabel("Email", { exact: true }).fill(researcher.email);
    await page.getByRole("button", { name: "Continue with email", exact: true }).click();
    await expect(page.getByRole("textbox", {name: "Verification code", exact: true})).toBeVisible();
    await page.getByRole("textbox", {name: "Verification code", exact: true}).fill(await emailCode(researcher.email));
    await page.getByRole("button", { name: "Verify and continue", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Allow OAuth acceptance client to access QAgentis?" })).toBeVisible();
    await expect(page.getByText("Create research runs and batches", { exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Allow access" }).click();
    await expect(page.getByText("Authorization complete. Return to QAgentis.")).toBeVisible();
    const returned = await received;
    expect(returned.searchParams.get("state")).toBe("oauth-acceptance");
    const issued = await external.post(`${base}/api/auth/oauth2/token`, { form: {
      grant_type: "authorization_code", client_id: client.client_id, code: returned.searchParams.get("code")!,
      code_verifier: verifier, redirect_uri: redirect, resource: `${base}/mcp`,
    } });
    expect(issued.status()).toBe(200);
    const tokens = await issued.json() as { access_token: string; refresh_token: string };
    const refreshed = await external.post("/api/auth/oauth2/token", {form: {
      grant_type: "refresh_token", client_id: client.client_id, refresh_token: tokens.refresh_token, resource: `${base}/mcp`,
    }});
    expect(refreshed.status()).toBe(200);
    const next = await refreshed.json();
    expect(typeof next.access_token).toBe("string");
    const revoked = await external.post("/api/auth/oauth2/revoke", {form: {client_id: client.client_id, token: next.refresh_token}});
    expect(revoked.status()).toBe(200);
    const denied = await external.post("/api/auth/oauth2/token", {form: {grant_type: "refresh_token", client_id: client.client_id, refresh_token: next.refresh_token, resource: `${base}/mcp`}});
    expect(denied.status()).toBe(400);
  } finally {
    await external.dispose();
    await new Promise<void>((resolve, reject) => callback.close(error => error ? reject(error) : resolve()));
  }
});
