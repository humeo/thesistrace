import http from "node:http";

const upstreamOrigin = requiredOrigin("THESISTRACE_MCP_PROXY_UPSTREAM");
const port = requiredPort("THESISTRACE_MCP_PROXY_PORT");
const upstreamTimeoutMs = 5_000;
let toolCallMode = "pass";
let discoveryRequests = 0;
let toolListRequests = 0;
let toolCallRequests = 0;
let disconnectedToolResponses = 0;
let disconnectedSubmitResponses = 0;
let metadataMode = "pass";
let metadataRequests = 0;
let disconnectedMetadataResponses = 0;

http.createServer(async (request, response) => {
  const url = new URL(request.url ?? "/", "http://mcp-fault-proxy.test");
  if (request.method === "GET" && url.pathname === "/health/live") {
    json(response, 200, { status: "ok" });
    return;
  }
  if (request.method === "GET" && url.pathname === "/__test/state") {
    json(response, 200, {
      disconnected_tool_responses: disconnectedToolResponses,
      disconnected_submit_responses: disconnectedSubmitResponses,
      disconnected_metadata_responses: disconnectedMetadataResponses,
      discovery_requests: discoveryRequests,
      metadata_mode: metadataMode,
      metadata_requests: metadataRequests,
      tool_call_mode: toolCallMode,
      tool_call_requests: toolCallRequests,
      tool_list_requests: toolListRequests,
    });
    return;
  }
  if (request.method === "PUT" && url.pathname === "/__test/metadata-mode") {
    const body = await readJson(request, 1_024);
    if (
      body === null
      || (body.mode !== "pass" && body.mode !== "disconnect")
      || typeof body.reset !== "boolean"
    ) {
      json(response, 400, { code: "MCP_PROXY_CONTROL_INVALID" });
      return;
    }
    metadataMode = body.mode;
    if (body.reset) {
      metadataRequests = 0;
      disconnectedMetadataResponses = 0;
    }
    json(response, 200, { metadata_mode: metadataMode });
    return;
  }
  if (
    request.method === "GET"
    && url.pathname === "/.well-known/oauth-protected-resource/mcp"
    && url.search === ""
  ) {
    metadataRequests += 1;
    try {
      const upstream = await fetch(new URL(url.pathname, upstreamOrigin), {
        headers: forwardedHeaders(request.headers),
        method: "GET",
        redirect: "manual",
        signal: AbortSignal.timeout(upstreamTimeoutMs),
      });
      const responseBody = new Uint8Array(await upstream.arrayBuffer());
      if (metadataMode === "disconnect") {
        disconnectedMetadataResponses += 1;
        response.destroy();
        return;
      }
      const responseHeaders = forwardedHeaders(upstream.headers);
      response.writeHead(upstream.status, Object.fromEntries(responseHeaders));
      response.end(responseBody);
    } catch {
      json(response, 502, { code: "MCP_PROXY_UPSTREAM_UNAVAILABLE" });
    }
    return;
  }
  if (request.method === "PUT" && url.pathname === "/__test/tool-call-mode") {
    const body = await readJson(request, 1_024);
    if (
      body === null
      || !["pass", "disconnect", "disconnect-submit"].includes(body.mode)
      || typeof body.reset !== "boolean"
    ) {
      json(response, 400, { code: "MCP_PROXY_CONTROL_INVALID" });
      return;
    }
    toolCallMode = body.mode;
    if (body.reset) {
      discoveryRequests = 0;
      toolListRequests = 0;
      toolCallRequests = 0;
      disconnectedToolResponses = 0;
      disconnectedSubmitResponses = 0;
    }
    json(response, 200, { tool_call_mode: toolCallMode });
    return;
  }
  if (url.pathname !== "/mcp" || url.search !== "") {
    json(response, 404, { code: "NOT_FOUND" });
    return;
  }

  const body = request.method === "POST"
    ? await readBytes(request, 1024 * 1024)
    : new Uint8Array();
  if (body === null) {
    json(response, 413, { code: "MCP_PROXY_REQUEST_TOO_LARGE" });
    return;
  }
  const methods = rpcMethods(body);
  const toolNames = rpcToolNames(body);
  if (methods.includes("initialize") || methods.includes("server/discover")) {
    discoveryRequests += 1;
  }
  if (methods.includes("tools/list")) toolListRequests += 1;
  if (methods.includes("tools/call")) toolCallRequests += 1;
  const disconnectSubmitResponse = toolCallMode === "disconnect-submit"
    && toolNames.some((name) => ["submit_research_run", "submit_research_batch"].includes(name));
  const disconnectResponse = methods.includes("tools/call")
    && (toolCallMode === "disconnect" || disconnectSubmitResponse);

  try {
    const headers = forwardedHeaders(request.headers);
    const upstream = await fetch(new URL("/mcp", upstreamOrigin), {
      body: body.byteLength === 0 ? undefined : body,
      headers,
      method: request.method,
      redirect: "manual",
      signal: AbortSignal.timeout(upstreamTimeoutMs),
    });
    const responseBody = new Uint8Array(await upstream.arrayBuffer());
    if (disconnectResponse) {
      disconnectedToolResponses += 1;
      if (disconnectSubmitResponse) disconnectedSubmitResponses += 1;
      response.destroy();
      return;
    }
    const responseHeaders = forwardedHeaders(upstream.headers);
    response.writeHead(upstream.status, Object.fromEntries(responseHeaders));
    response.end(responseBody);
  } catch {
    json(response, 502, { code: "MCP_PROXY_UPSTREAM_UNAVAILABLE" });
  }
}).listen(port, "0.0.0.0");

function forwardedHeaders(source) {
  const headers = new Headers();
  const entries = source instanceof Headers
    ? source.entries()
    : Object.entries(source);
  for (const [name, rawValue] of entries) {
    if ([
      "connection",
      "content-length",
      "host",
      "keep-alive",
      "transfer-encoding",
    ].includes(name.toLowerCase())) continue;
    if (Array.isArray(rawValue)) {
      for (const value of rawValue) headers.append(name, value);
    } else if (rawValue !== undefined) {
      headers.set(name, rawValue);
    }
  }
  return headers;
}

async function readJson(request, maxBytes) {
  const bytes = await readBytes(request, maxBytes);
  if (bytes === null) return null;
  try {
    const value = JSON.parse(Buffer.from(bytes).toString("utf8"));
    return value !== null && typeof value === "object" && !Array.isArray(value)
      ? value
      : null;
  } catch {
    return null;
  }
}

async function readBytes(request, maxBytes) {
  const chunks = [];
  let bytes = 0;
  for await (const chunk of request) {
    bytes += chunk.length;
    if (bytes > maxBytes) return null;
    chunks.push(chunk);
  }
  return new Uint8Array(Buffer.concat(chunks));
}

function rpcMethods(body) {
  if (body.byteLength === 0) return [];
  try {
    const value = JSON.parse(Buffer.from(body).toString("utf8"));
    const messages = Array.isArray(value) ? value : [value];
    return messages.flatMap((message) => (
      message !== null
      && typeof message === "object"
      && !Array.isArray(message)
      && typeof message.method === "string"
        ? [message.method]
        : []
    ));
  } catch {
    return [];
  }
}

function rpcToolNames(body) {
  if (body.byteLength === 0) return [];
  try {
    const value = JSON.parse(Buffer.from(body).toString("utf8"));
    const messages = Array.isArray(value) ? value : [value];
    return messages.flatMap((message) => (
      message !== null
      && typeof message === "object"
      && !Array.isArray(message)
      && message.method === "tools/call"
      && message.params !== null
      && typeof message.params === "object"
      && !Array.isArray(message.params)
      && typeof message.params.name === "string"
        ? [message.params.name]
        : []
    ));
  } catch {
    return [];
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
