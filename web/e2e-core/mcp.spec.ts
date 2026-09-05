import { createHash, randomBytes } from "node:crypto";
import { request as apiRequest } from "@playwright/test";
import { createServer } from "node:http";
import { test, expect, sameOriginHeaders, fillPasswordInput } from "./auth-fixture";

test("MCP product connects an external client through login, consent, discovery and revocation", async ({ page, researcher }, testInfo) => {
  test.setTimeout(90_000);
  const base = process.env.THESISTRACE_TEST_WEB_ORIGIN!;
  await page.goto("/connections/mcp");
  await expect(page.getByRole("heading", { name: "MCP", exact: true })).toBeVisible();
  await expect(page.getByText("Available", { exact: true })).toBeVisible();
  await expect(page.getByText(`${base}/mcp`, { exact: true })).toBeVisible();
  await expect(page.getByText("No authorized apps yet")).toBeVisible();
  await page.getByText("View setup prompt", { exact: true }).click();
  await expect(page.locator(".mcp-agent-prompt")).toContainText("Add ThesisTrace MCP to Codex");
  await expect(page.locator(".mcp-agent-prompt")).not.toContainText(".example");
  await page.screenshot({ path: testInfo.outputPath("mcp-desktop.png"), fullPage: true, animations: "disabled" });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("mcp-mobile.png"), fullPage: true, animations: "disabled" });
  await page.setViewportSize({ width: 1280, height: 960 });

  let receive: (url: URL) => void = () => undefined;
  const received = new Promise<URL>(resolve => { receive = resolve; });
  const callback = createServer((request, response) => {
    receive(new URL(request.url!, "http://127.0.0.1"));
    response.writeHead(200, { "content-type": "text/html", "cache-control": "no-store" });
    response.end("<p>Authorization complete. Return to ThesisTrace.</p>");
  });
  await new Promise<void>(resolve => callback.listen(0, "127.0.0.1", resolve));
  const external = await apiRequest.newContext({ baseURL: base });
  try {
    const address = callback.address();
    if (!address || typeof address === "string") throw Error("callback not listening");
    const redirect = `http://127.0.0.1:${address.port}/callback`;
    const registration = await external.post("/api/auth/oauth2/register", { data: {
      client_name: "MCP acceptance client", application_type: "native", token_endpoint_auth_method: "none",
      redirect_uris: [redirect], grant_types: ["authorization_code", "refresh_token"], response_types: ["code"],
    } });
    expect(registration.status()).toBe(201);
    const client = await registration.json() as { client_id: string };
    const verifier = randomBytes(32).toString("base64url");
    const query = new URLSearchParams({ client_id: client.client_id, response_type: "code", redirect_uri: redirect,
      scope: "research:read tracking:read offline_access", resource: `${base}/mcp`, state: "mcp-acceptance",
      code_challenge_method: "S256", code_challenge: createHash("sha256").update(verifier).digest("base64url") });
    await page.context().clearCookies();
    await page.goto(`/api/auth/oauth2/authorize?${query}`);
    await expect(page.getByRole("heading", { name: "Log in to ThesisTrace" })).toBeVisible();
    await page.getByLabel("Email", { exact: true }).fill(researcher.email);
    await fillPasswordInput(page.getByLabel("Password", { exact: true }));
    await page.getByRole("button", { name: "Log in", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Allow MCP acceptance client to access ThesisTrace?" })).toBeVisible();
    await expect(page.getByText("Create research runs and batches", { exact: true })).toHaveCount(0);
    await page.screenshot({ path: testInfo.outputPath("mcp-consent.png"), fullPage: true, animations: "disabled" });
    await page.getByRole("button", { name: "Allow access" }).click();
    await expect(page.getByText("Authorization complete. Return to ThesisTrace.")).toBeVisible();
    const returned = await received;
    expect(returned.searchParams.get("state")).toBe("mcp-acceptance");
    const issued = await external.post(`${base}/api/auth/oauth2/token`, { form: {
      grant_type: "authorization_code", client_id: client.client_id, code: returned.searchParams.get("code")!,
      code_verifier: verifier, redirect_uri: redirect, resource: `${base}/mcp`,
    } });
    expect(issued.status()).toBe(200);
    const tokens = await issued.json() as { access_token: string };
    const headers = { authorization: `Bearer ${tokens.access_token}`, accept: "application/json, text/event-stream" };
    const initialized = await external.post(`${base}/mcp`, { headers, data: {
      jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2026-07-28", capabilities: {}, clientInfo: { name: "acceptance", version: "1" } },
    } });
    expect(initialized.status()).toBe(200);
    const negotiated = await initialized.json() as { result: { protocolVersion: string } };
    const tools = await external.post(`${base}/mcp`, { headers: { ...headers, "MCP-Protocol-Version": negotiated.result.protocolVersion }, data: { jsonrpc: "2.0", id: 2, method: "tools/list", params: {} } });
    expect(tools.status()).toBe(200);
    const listing = await tools.json() as { result: { tools: { name: string }[] } };
    expect(listing.result.tools.some(tool => tool.name === "get_research_context")).toBe(true);
    expect(listing.result.tools.some(tool => tool.name === "submit_research_run")).toBe(false);
    await page.goto(`${base}/connections/mcp`);
    await expect(page.locator(".mcp-app")).toContainText("MCP acceptance client");
    await page.getByRole("button", { name: "Revoke access for MCP acceptance client" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Revoke access", exact: true }).click();
    await expect(page.getByText("No authorized apps yet")).toBeVisible();
    const rejected = await external.post(`${base}/mcp`, { headers, data: { jsonrpc: "2.0", id: 3, method: "tools/list", params: {} } });
    expect(rejected.status()).toBe(401);
    expect((await page.request.get(`${base}/api/auth/mcp/connections`, { headers: sameOriginHeaders() })).status()).toBe(200);
  } finally { await external.dispose(); await new Promise<void>((resolve, reject) => callback.close(error => error ? reject(error) : resolve())); }
});
