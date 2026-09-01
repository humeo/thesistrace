import http from "node:http";

const researcher = {
  active: true,
  display_label: "Image Researcher",
  email: "image@example.test",
  researcher_id: "00000000-0000-4000-8000-000000000101",
};
const validCookie = "thesistrace.session_token=image-smoke-session";
const accessToken = "image-smoke-mcp-access-token";

http.createServer((request, response) => {
  if (request.method === "GET" && request.url === "/health/ready") {
    json(response, 200, { status: "ready" });
    return;
  }
  if (request.method !== "POST") {
    response.writeHead(404).end();
    return;
  }
  if (request.headers.cookie !== validCookie) {
    response.writeHead(401).end();
    return;
  }
  if (request.url === "/internal/session/verify") {
    json(response, 200, researcher);
    return;
  }
  if (request.url === "/internal/session/exchange") {
    json(response, 200, {
      access_token: accessToken,
      expires_in: 660,
      token_type: "Bearer",
    }, { "cache-control": "no-store" });
    return;
  }
  response.writeHead(404).end();
}).listen(8200, "0.0.0.0");

http.createServer(async (request, response) => {
  if (
    request.method === "GET"
    && request.url === "/.well-known/oauth-protected-resource/mcp"
  ) {
    json(response, 200, {
      authorization_servers: ["https://thesistrace.test/api/auth"],
      resource: "https://thesistrace.test/mcp",
    });
    return;
  }
  if (request.url !== "/mcp") {
    response.writeHead(404).end();
    return;
  }
  if (request.headers.authorization !== `Bearer ${accessToken}`) {
    response.writeHead(401).end();
    return;
  }
  if (request.method === "DELETE") {
    response.writeHead(204).end();
    return;
  }
  if (request.method !== "POST") {
    response.writeHead(405).end();
    return;
  }
  let body = "";
  for await (const chunk of request) {
    body += chunk;
    if (Buffer.byteLength(body) > 64 * 1024) {
      response.writeHead(413).end();
      return;
    }
  }
  let message;
  try {
    message = JSON.parse(body);
  } catch {
    response.writeHead(400).end();
    return;
  }
  if (message.method === "server/discover") {
    rpc(response, message.id, {
      _meta: {
        "io.modelcontextprotocol/serverInfo": {
          name: "ThesisTrace image MCP",
          version: "1.0.0",
        },
      },
      cacheScope: "private",
      capabilities: { tools: {} },
      supportedVersions: ["2026-07-28"],
      ttlMs: 0,
    });
    return;
  }
  if (message.method === "tools/list") {
    rpc(response, message.id, {
      cacheScope: "private",
      tools: [{
        description: "Read the image-smoke research context.",
        inputSchema: { additionalProperties: false, properties: {}, type: "object" },
        name: "get_research_context",
        outputSchema: {
          additionalProperties: false,
          properties: { dataset: { type: "string" } },
          required: ["dataset"],
          type: "object",
        },
      }],
      ttlMs: 0,
    });
    return;
  }
  if (message.method === "tools/call" && message.params?.name === "get_research_context") {
    rpc(response, message.id, {
      _meta: { "thesistrace/tool-outcome": "succeeded" },
      content: [{
        text: JSON.stringify({ dataset: "image-smoke-private-mcp-result" }),
        type: "text",
      }],
      isError: false,
      structuredContent: { dataset: "image-smoke-private-mcp-result" },
    });
    return;
  }
  json(response, 200, {
    error: { code: -32601, message: "Method not found" },
    id: message.id ?? null,
    jsonrpc: "2.0",
  });
}).listen(8500, "0.0.0.0");

function rpc(response, id, result) {
  json(response, 200, {
    id,
    jsonrpc: "2.0",
    result: { ...result, resultType: "complete" },
  });
}

function json(response, status, value, headers = {}) {
  response.writeHead(status, { "content-type": "application/json", ...headers });
  response.end(JSON.stringify(value));
}
