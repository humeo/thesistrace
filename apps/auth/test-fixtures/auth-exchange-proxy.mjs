import http from "node:http";

const upstreamOrigin = requiredOrigin("THESISTRACE_AUTH_PROXY_UPSTREAM");
const port = requiredPort("THESISTRACE_AUTH_PROXY_PORT");
const upstreamTimeoutMs = 5_000;
let exchangeMode = "pass";
let exchangeRequests = 0;
let delayedExchangeResponses = 0;
let readinessMode = "pass";
let readinessRequests = 0;
let disconnectedReadinessResponses = 0;

http.createServer(async (request, response) => {
  const url = new URL(request.url ?? "/", "http://auth-exchange-proxy.test");
  if (request.method === "GET" && url.pathname === "/health/live") {
    json(response, 200, { status: "ok" });
    return;
  }
  if (request.method === "GET" && url.pathname === "/__test/state") {
    json(response, 200, {
      delayed_exchange_responses: delayedExchangeResponses,
      disconnected_readiness_responses: disconnectedReadinessResponses,
      exchange_mode: exchangeMode,
      exchange_requests: exchangeRequests,
      readiness_mode: readinessMode,
      readiness_requests: readinessRequests,
    });
    return;
  }
  if (request.method === "PUT" && url.pathname === "/__test/readiness-mode") {
    const body = await readJson(request, 1_024);
    if (
      body === null
      || (body.mode !== "pass" && body.mode !== "disconnect")
      || typeof body.reset !== "boolean"
    ) {
      json(response, 400, { code: "AUTH_PROXY_CONTROL_INVALID" });
      return;
    }
    readinessMode = body.mode;
    if (body.reset) {
      readinessRequests = 0;
      disconnectedReadinessResponses = 0;
    }
    json(response, 200, { readiness_mode: readinessMode });
    return;
  }
  const isReadiness = url.pathname === "/health/ready";
  const isQuotaPolicy = /^\/internal\/researchers\/[^/]+\/quota-policy$/.test(url.pathname);
  if (
    request.method === "GET"
    && (isReadiness || isQuotaPolicy)
    && url.search === ""
  ) {
    if (isReadiness) readinessRequests += 1;
    try {
      const upstream = await fetch(new URL(url.pathname, upstreamOrigin), {
        method: "GET",
        redirect: "manual",
        signal: AbortSignal.timeout(upstreamTimeoutMs),
      });
      const body = new Uint8Array(await upstream.arrayBuffer());
      if (isReadiness && readinessMode === "disconnect") {
        disconnectedReadinessResponses += 1;
        response.destroy();
        return;
      }
      forwardResponse(response, upstream, body);
    } catch {
      json(response, 502, { code: "AUTH_PROXY_UPSTREAM_UNAVAILABLE" });
    }
    return;
  }
  if (request.method === "PUT" && url.pathname === "/__test/exchange-mode") {
    const body = await readJson(request, 1_024);
    if (
      body === null
      || (body.mode !== "pass" && body.mode !== "timeout")
      || typeof body.reset !== "boolean"
    ) {
      json(response, 400, { code: "AUTH_PROXY_CONTROL_INVALID" });
      return;
    }
    exchangeMode = body.mode;
    if (body.reset) {
      exchangeRequests = 0;
      delayedExchangeResponses = 0;
    }
    json(response, 200, { exchange_mode: exchangeMode });
    return;
  }
  if (
    request.method !== "POST"
    || (url.pathname !== "/internal/session/verify"
      && url.pathname !== "/internal/session/exchange")
    || url.search !== ""
  ) {
    json(response, 404, { code: "NOT_FOUND" });
    return;
  }

  const isExchange = url.pathname === "/internal/session/exchange";
  const delayResponse = isExchange && exchangeMode === "timeout";
  if (isExchange) exchangeRequests += 1;
  try {
    const headers = new Headers();
    if (request.headers.cookie !== undefined) {
      headers.set("cookie", request.headers.cookie);
    }
    const upstream = await fetch(new URL(url.pathname, upstreamOrigin), {
      headers,
      method: "POST",
      redirect: "manual",
      signal: AbortSignal.timeout(upstreamTimeoutMs),
    });
    const body = new Uint8Array(await upstream.arrayBuffer());
    if (delayResponse) {
      delayedExchangeResponses += 1;
      await waitForClientDisconnect(request, response);
      return;
    }
    forwardResponse(response, upstream, body);
  } catch {
    json(response, 502, { code: "AUTH_PROXY_UPSTREAM_UNAVAILABLE" });
  }
}).listen(port, "0.0.0.0");

function waitForClientDisconnect(request, response) {
  if (request.aborted || response.destroyed) return Promise.resolve();
  return new Promise((resolve) => {
    let settled = false;
    const done = () => {
      if (settled) return;
      settled = true;
      request.off("aborted", done);
      request.off("close", done);
      response.off("close", done);
      resolve();
    };
    request.once("aborted", done);
    request.once("close", done);
    response.once("close", done);
    if (request.aborted || response.destroyed) done();
  });
}

function forwardResponse(response, upstream, body) {
  const responseHeaders = new Headers();
  for (const name of ["cache-control", "content-type"]) {
    const value = upstream.headers.get(name);
    if (value !== null) responseHeaders.set(name, value);
  }
  response.writeHead(upstream.status, Object.fromEntries(responseHeaders));
  response.end(body);
}

async function readJson(request, maxBytes) {
  const chunks = [];
  let bytes = 0;
  for await (const chunk of request) {
    bytes += chunk.length;
    if (bytes > maxBytes) return null;
    chunks.push(chunk);
  }
  try {
    const value = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    return value !== null && typeof value === "object" && !Array.isArray(value)
      ? value
      : null;
  } catch {
    return null;
  }
}

function json(response, status, body) {
  response.writeHead(status, { "content-type": "application/json" });
  response.end(JSON.stringify(body));
}

function requiredOrigin(name) {
  const value = process.env[name];
  if (value === undefined) throw new Error(`${name} is required`);
  const url = new URL(value);
  if (url.protocol !== "http:" || url.pathname !== "/" || url.search || url.hash) {
    throw new Error(`${name} is invalid`);
  }
  return url;
}

function requiredPort(name) {
  const value = Number(process.env[name]);
  if (!Number.isInteger(value) || value < 1 || value > 65_535) {
    throw new Error(`${name} is invalid`);
  }
  return value;
}
