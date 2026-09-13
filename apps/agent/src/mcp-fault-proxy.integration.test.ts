import { spawn } from "node:child_process";
import { createServer, type Server } from "node:http";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";

async function listen(server: Server): Promise<number> {
  await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("No test listener");
  return address.port;
}
async function close(server: Server) {
  server.closeAllConnections();
  await new Promise<void>(resolve => server.close(() => resolve()));
}

it.each(["pass", "hold"])("does not enqueue a late upstream response into a released barrier (%s)", async mode => {
  let entered!: () => void;
  let release!: () => void;
  const received = new Promise<void>(resolve => { entered = resolve; });
  const available = new Promise<void>(resolve => { release = resolve; });
  const upstream = createServer(async (_request, response) => {
    entered();
    await available;
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ jsonrpc: "2.0", id: 1, result: { content: [] } }));
  });
  const upstreamPort = await listen(upstream);
  const reservation = createServer();
  const port = await listen(reservation);
  await close(reservation);
  const proxy = spawn(process.execPath, [fileURLToPath(new URL("../test-fixtures/mcp-fault-proxy.mjs", import.meta.url))], {
    env: { THESISTRACE_MCP_PROXY_UPSTREAM: `http://127.0.0.1:${upstreamPort}`, THESISTRACE_MCP_PROXY_PORT: String(port) },
    stdio: "ignore",
  });
  const exited = new Promise<void>(resolve => proxy.once("exit", () => resolve()));
  const origin = `http://127.0.0.1:${port}`;
  const setMode = async (value: string) => {
    const result = await fetch(`${origin}/__test/tool-call-mode`, { method: "PUT",
      headers: { "content-type": "application/json" }, body: JSON.stringify({ mode: value, reset: true }) });
    expect(result.status).toBe(200);
    await result.arrayBuffer();
  };
  let response: Promise<Response> | undefined;
  try {
    await expect.poll(async () => {
      try { return (await fetch(`${origin}/health/live`)).ok; } catch { return false; }
    }, { timeout: 5_000 }).toBe(true);
    await setMode("hold");
    response = fetch(`${origin}/mcp`, { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "get_research_context", arguments: {} } }),
      signal: AbortSignal.timeout(2_000) });
    void response.catch(() => undefined);
    await received;
    await setMode(mode);
    release();
    const forwarded = await response;
    expect(forwarded.status).toBe(200);
    expect(await forwarded.json()).toEqual({ jsonrpc: "2.0", id: 1, result: { content: [] } });
    const state = await (await fetch(`${origin}/__test/state`)).json();
    expect(state.pending_held_tool_responses).toBe(0);
  } finally {
    release();
    proxy.kill("SIGTERM");
    await exited;
    await response?.catch(() => undefined);
    await close(upstream);
  }
}, 10_000);
