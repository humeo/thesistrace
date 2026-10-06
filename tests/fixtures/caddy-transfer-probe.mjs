import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import http from "node:http";
import https from "node:https";
import { gunzipSync, zstdDecompressSync } from "node:zlib";

const pendingStreams = new Map();
const json = JSON.stringify({ content: "public transfer fixture ".repeat(100) });
const routes = [
  { path: "/api/auth/transfer-probe", port: 8200 },
  { path: "/api/transfer-probe", port: 8100 },
  { path: "/api/agent/transfer-probe", port: 8400 },
  { path: "/mcp", port: 8100 },
];

/** Synthetic upstream used only inside the isolated Caddy image check. */
export function handleTransfer(request, response) {
  if (request.url === "/internal/operator/page-access") {
    response.writeHead(request.headers.cookie === "session=operator-allowed" ? 204 : 404).end();
  } else if (request.url.startsWith("/probe/release/")) {
    const stream = pendingStreams.get(request.url.slice("/probe/release/".length));
    if (!stream) response.writeHead(404).end();
    else {
      stream.end("data: last\n\n");
      response.end("released");
    }
  } else if (routes.some(route => route.path === request.url)) {
    if (request.headers.accept === "text/event-stream") {
      const id = request.headers["x-transfer-id"];
      pendingStreams.set(id, response);
      response.on("close", () => pendingStreams.delete(id));
      response.writeHead(200, { "content-type": "text/event-stream" });
      response.write("data: first\n\n");
      // Only the client observing the first event may release the final event.
      // A buffered proxy therefore fails the request's bounded timeout.
    } else {
      response.writeHead(200, { "content-type": "application/json" }).end(json);
    }
  } else return false;
  return true;
}

export async function qualifyTransfers() {
  const origin = "https://thesistrace.test";
  const html = await send(`${origin}/data`, { "accept-encoding": "identity" });
  assert.equal(html.status, 200);
  const assets = [...html.body.toString().matchAll(/(?:src|href)="(\/assets\/[^" ]+\.(?:js|css))"/g)].map(match => match[1]);
  assert.ok(assets.some(path => path.endsWith(".js")), "Product HTML must reference its JavaScript entry");
  assert.ok(assets.some(path => path.endsWith(".css")), "Product HTML must reference its CSS");
  const staticResults = [];
  for (const path of ["/data", "/operator/data", ...new Set(assets)]) {
    const headers = path.startsWith("/operator/") ? { cookie: "session=operator-allowed" } : {};
    const plain = await send(`${origin}${path}`, { ...headers, "accept-encoding": "identity" });
    const cache = path.startsWith("/assets/") ? "public, max-age=31536000, immutable" : "no-cache";
    assert.equal(plain.status, 200, path);
    assert.equal(plain.headers["cache-control"], cache, path);
    assert.equal(plain.headers["content-encoding"], undefined, path);
    for (const [encoding, decode] of [["gzip", gunzipSync], ["zstd", zstdDecompressSync]]) {
      const compressed = await send(`${origin}${path}`, { ...headers, "accept-encoding": encoding });
      assert.equal(compressed.status, 200, path);
      assert.equal(compressed.headers["content-encoding"], encoding, `${path} must use ${encoding}`);
      assert.equal(compressed.headers["cache-control"], cache, path);
      assert.match(compressed.headers.vary, /accept-encoding/i);
      assert.deepEqual(decode(compressed.body), plain.body, `${path} decoded bytes`);
      assert.ok(compressed.body.length < plain.body.length, `${path} wire bytes must shrink`);
      assert.ok(compressed.headers.etag, `${path} needs an encoding-specific validator`);
      const cached = await send(`${origin}${path}`, { ...headers, "accept-encoding": encoding, "if-none-match": compressed.headers.etag });
      assert.equal(cached.status, 304, `${path} conditional ${encoding} response`);
      assert.equal(cached.body.length, 0);
      assert.equal(cached.headers["cache-control"], cache);
      staticResults.push({ path, encoding, rawBytes: plain.body.length, wireBytes: compressed.body.length });
    }
  }
  const apiResults = [];
  for (const { path, port } of routes) {
    const normal = await send(`${origin}${path}`, { "accept-encoding": "zstd, gzip" });
    assert.equal(normal.status, 200, path);
    assert.equal(normal.headers["cache-control"], "no-store", path);
    assert.equal(normal.headers["content-encoding"], undefined, `${path} API encoding`);
    assert.equal(normal.body.toString(), json, path);
    const id = randomUUID();
    let received = "", release;
    const stream = await send(`${origin}${path}`, {
      "accept-encoding": "zstd, gzip", accept: "text/event-stream", "x-transfer-id": id,
    }, chunk => {
      received += chunk.toString();
      if (!release && received.includes("data: first\n\n")) {
        release = send(`http://127.0.0.1:${port}/probe/release/${id}`);
        return release;
      }
    });
    assert.equal(stream.status, 200, path);
    assert.equal(stream.headers["cache-control"], "no-store", path);
    assert.equal(stream.headers["content-encoding"], undefined, `${path} stream encoding`);
    assert.ok(release, `${path} first event must arrive before the stream closes`);
    assert.equal((await release).status, 200);
    assert.equal(stream.body.toString(), "data: first\n\ndata: last\n\n", path);
    apiResults.push({ path, streamedBeforeClose: true, bytes: normal.body.length });
  }
  return { static: staticResults, api: apiResults };
}

function send(url, headers = {}, onChunk = () => {}) {
  return new Promise((resolve, reject) => {
    const client = url.startsWith("https:") ? https : http;
    const request = client.get(url, {
      headers, agent: false, rejectUnauthorized: false,
    }, response => {
      const chunks = [];
      response.on("data", chunk => {
        chunks.push(chunk);
        Promise.resolve(onChunk(chunk)).catch(error => request.destroy(error));
      });
      response.on("end", () => resolve({ status: response.statusCode, headers: response.headers, body: Buffer.concat(chunks) }));
      response.on("error", reject);
    });
    request.on("error", reject);
    request.setTimeout(10_000, () => request.destroy(new Error(`Caddy transfer timed out: ${new URL(url).pathname}`)));
  });
}
