import { createServer } from "node:http";

const allowedModes = new Set(["success", "rejected", "delayed", "unavailable"]);
const configuredPort = parsePort(process.env.THESISTRACE_RESEND_FAKE_PORT ?? "8300");
const configuredHost = parseHost(
  process.env.THESISTRACE_RESEND_FAKE_HOST ?? "127.0.0.1",
);
let mode = parseMode(process.env.THESISTRACE_RESEND_FAKE_MODE ?? "success");
let sequence = 0;
const emails = [];

const server = createServer(async (request, response) => {
  const url = new URL(request.url ?? "/", "http://resend-fake.test");
  if (request.method === "GET" && url.pathname === "/health/live") {
    return json(response, 200, { status: "ok" });
  }
  if (request.method === "GET" && url.pathname === "/__test/emails") {
    return json(response, 200, { emails });
  }
  if (request.method === "DELETE" && url.pathname === "/__test/emails") {
    emails.length = 0;
    return json(response, 200, { status: true });
  }
  if (request.method === "PUT" && url.pathname === "/__test/mode") {
    const body = await readJson(request);
    if (body === null || typeof body.mode !== "string" || !allowedModes.has(body.mode)) {
      return json(response, 400, { code: "RESEND_FAKE_REQUEST_INVALID" });
    }
    mode = body.mode;
    return json(response, 200, { mode });
  }
  if (request.method !== "POST" || url.pathname !== "/emails") {
    return json(response, 404, { code: "NOT_FOUND" });
  }

  const body = await readJson(request);
  if (body === null) {
    return json(response, 400, { code: "RESEND_FAKE_REQUEST_INVALID" });
  }
  emails.push(body);
  if (mode === "unavailable") {
    request.socket.destroy();
    return;
  }
  if (mode === "delayed") {
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  if (mode === "rejected") {
    return json(response, 422, { code: "RESEND_FAKE_REJECTED" });
  }
  sequence += 1;
  return json(response, 200, { id: `resend-fake-${sequence}` });
});

server.listen(configuredPort, configuredHost, () => {
  const address = server.address();
  if (address === null || typeof address === "string") {
    process.exitCode = 1;
    return;
  }
  process.stdout.write(
    `${JSON.stringify({ event: "resend_fake_ready", port: address.port })}\n`,
  );
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.once(signal, () => {
    server.close(() => {
      process.exitCode = 0;
    });
  });
}

async function readJson(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > 1024 * 1024) {
      request.destroy();
      return null;
    }
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

function parseMode(value) {
  if (!allowedModes.has(value)) {
    throw new Error("THESISTRACE_RESEND_FAKE_MODE_INVALID");
  }
  return value;
}

function parsePort(value) {
  const port = Number(value);
  if (!Number.isInteger(port) || port < 0 || port > 65535) {
    throw new Error("THESISTRACE_RESEND_FAKE_PORT_INVALID");
  }
  return port;
}

function parseHost(value) {
  if (value !== "127.0.0.1" && value !== "0.0.0.0") {
    throw new Error("THESISTRACE_RESEND_FAKE_HOST_INVALID");
  }
  return value;
}
