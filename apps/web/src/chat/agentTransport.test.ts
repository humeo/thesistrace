import { expect, test, vi } from "vitest";
import { createAgentFetch } from "./agentTransport";

test.each([
  [401, "AUTHENTICATION_REQUIRED"], [400, "INVALID_MODEL"], [400, "UNSUPPORTED_REASONING"],
  [404, "CHAT_SESSION_NOT_FOUND"], [413, "AGENT_LIMIT"], [503, "AGENT_UNAVAILABLE"],
])("projects safe HTTP failure %s into exactly one terminal event", async (status, code) => {
  const fetch = vi.fn(async () => Response.json({ code, private: "secret-canary" }, { status }));
  const response = await createAgentFetch(fetch)("/api/agent/copilotkit/agent/research/run", { method: "POST" });
  const text = await response.text();
  expect(response.status).toBe(200);
  expect(response.headers.get("content-type")).toContain("text/event-stream");
  expect(text.match(/RUN_ERROR/g)).toHaveLength(1);
  expect(text).toContain(code);
  expect(text).not.toMatch(/secret-canary|RUN_STARTED|RUN_FINISHED/);
  expect(fetch).toHaveBeenCalledOnce();
});

test("valid streaming connections are untouched and do not retain the header timeout", async () => {
  vi.useFakeTimers();
  try {
    const stream = new Response("data: {}\n\n", { headers: { "content-type": "text/event-stream" } });
    let signal: AbortSignal | null | undefined;
    const response = await createAgentFetch(async (_url, init) => { signal = init.signal; return stream; })("/run", {});
    await vi.advanceTimersByTimeAsync(6_000);
    expect(response).toBe(stream);
    expect(signal?.aborted).toBe(false);
  } finally { vi.useRealTimers(); }
});

test("bounds a stalled error body and never returns its raw content", async () => {
  vi.useFakeTimers();
  try {
    const response = new Response(new ReadableStream({ start() {} }), { status: 400 });
    const pending = createAgentFetch(async () => response)("/run", {});
    await vi.advanceTimersByTimeAsync(5_001);
    expect(await (await pending).text()).toContain("AGENT_UNAVAILABLE");
  } finally { vi.useRealTimers(); }
});

test("network uncertainty never replays a request or invents provider failure", async () => {
  const fetch = vi.fn(async () => { throw new Error("private-network-detail"); });
  const response = await createAgentFetch(fetch)("/run", {});
  expect(await response.text()).toContain("AGENT_UNAVAILABLE");
  expect(fetch).toHaveBeenCalledOnce();
});
