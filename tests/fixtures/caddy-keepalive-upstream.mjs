import assert from "node:assert/strict";
import http from "node:http";
import https from "node:https";
import { setTimeout as pollInterval } from "node:timers/promises";

const cases = [
  { kind: "auth", port: 8200, path: "/api/auth/keepalive-probe", idleMilliseconds: 6_000 },
  { kind: "core", port: 8100, path: "/api/keepalive-probe", idleMilliseconds: 5_000 },
];

if (process.argv[2] === "serve") {
  for (const probe of cases) startUpstream(probe);
} else if (process.argv[2] === "probe") {
  const results = [];
  for (const probe of cases) results.push(await qualifyIdlePost(probe));
  console.log(JSON.stringify({ keepalive: results }));
  assert.ok(results.every((result) => result.status === 202), "Expired upstream connection must not turn a POST into HTTP 502");
  assert.ok(results.every((result) => result.receivedPosts === 2), "The gateway must not retry a mutation after a failed round trip");
} else {
  throw new Error("Expected serve or probe");
}

function startUpstream({ port, path, idleMilliseconds }) {
  const connections = new Map();
  const socketIds = new WeakMap();
  let receivedPosts = 0;
  const server = http.createServer(async (request, response) => {
    const url = new URL(request.url, "http://probe.test");
    if (url.pathname === "/probe/health") {
      response.end("ready");
      return;
    }
    if (url.pathname === "/probe/expired") {
      const state = connections.get(Number(url.searchParams.get("connection")));
      if (state === undefined) {
        response.writeHead(404).end();
        return;
      }
      await state.expiration;
      response.end("expired");
      return;
    }
    if (request.method !== "POST" || url.pathname !== path) {
      response.writeHead(404).end();
      return;
    }
    receivedPosts += 1;
    const connection = socketIds.get(request.socket);
    const state = connections.get(connection);
    if (state.expired) {
      // Hold the upstream's idle close until reuse, making the in-flight FIN
      // race deterministic. No application response or retry is supplied.
      request.socket.destroy();
      return;
    }
    for await (const _chunk of request) { /* Drain the synthetic POST body. */ }
    response.writeHead(202, { "content-type": "application/json" });
    response.end(JSON.stringify({ connection, receivedPosts }));
    setTimeout(() => {
      state.expired = true;
      state.expire();
    }, idleMilliseconds).unref();
  });
  // The fixture controls the close race explicitly; it is never an Auth server.
  server.keepAliveTimeout = 0;
  server.on("connection", (socket) => {
    const connection = connections.size + 1;
    let expire;
    const expiration = new Promise((resolve) => { expire = resolve; });
    connections.set(connection, { expired: false, expiration, expire });
    socketIds.set(socket, connection);
  });
  server.listen(port, "0.0.0.0");
}

async function qualifyIdlePost({ kind, port, path }) {
  const upstream = `http://127.0.0.1:${port}`;
  const gateway = `https://thesistrace.test${path}`;
  const deadline = Date.now() + 10_000;
  while (true) {
    try {
      assert.equal((await send(`${upstream}/probe/health`)).status, 200);
      break;
    } catch (error) {
      if (Date.now() >= deadline) throw error;
      await pollInterval(50);
    }
  }
  const warm = await send(gateway, "POST");
  assert.equal(warm.status, 202, `${kind} warm request`);
  const { connection } = JSON.parse(warm.body);
  // A bounded long poll waits for the actual fixture expiry event, not a sleep.
  const expired = await send(`${upstream}/probe/expired?connection=${connection}`);
  assert.equal(expired.status, 200);
  const next = await send(gateway, "POST");
  const body = next.status === 202 ? JSON.parse(next.body) : null;
  return { kind, status: next.status, receivedPosts: body?.receivedPosts ?? null };
}

function send(url, method = "GET") {
  return new Promise((resolve, reject) => {
    const client = url.startsWith("https:") ? https : http;
    const request = client.request(url, {
      method,
      agent: false,
      // The enclosing smoke uses its isolated, internal Caddy test CA.
      rejectUnauthorized: false,
      headers: method === "POST" ? { "content-type": "application/json" } : {},
    }, (response) => {
      let body = "";
      response.setEncoding("utf8");
      response.on("data", (chunk) => { body += chunk; });
      response.on("end", () => resolve({ status: response.statusCode, body }));
      response.on("error", reject);
    });
    request.on("error", reject);
    request.setTimeout(10_000, () => request.destroy(new Error("Keepalive probe timed out")));
    request.end(method === "POST" ? "{}" : undefined);
  });
}
