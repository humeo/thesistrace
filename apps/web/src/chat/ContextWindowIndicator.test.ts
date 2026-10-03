import { afterEach, expect, it, vi } from "vitest";
import { loadContextWindow } from "./ContextWindowIndicator";

afterEach(() => vi.unstubAllGlobals());

it("loads the selected model's measured input and keeps unmeasured usage unknown", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(Response.json({ model_key: "luna", context_window: 258_000, input_tokens: 92_000, measured_at: "2026-10-02T08:00:00.000Z" }))
    .mockResolvedValueOnce(Response.json({ model_key: "luna", context_window: 258_000, input_tokens: null, measured_at: null }));
  vi.stubGlobal("fetch", fetch);
  const measured = await loadContextWindow("luna", "thread-id", new AbortController().signal);
  expect(measured.input_tokens).toBe(92_000);
  expect(fetch.mock.calls[0][0]).toBe("/api/agent/context-window?model_key=luna&thread_id=thread-id");
  expect((await loadContextWindow("luna", null, new AbortController().signal)).input_tokens).toBeNull();
});

it.each([
  { model_key: "other", context_window: 258_000, input_tokens: 92_000, measured_at: "2026-10-02T08:00:00.000Z" },
  { model_key: "luna", context_window: 0, input_tokens: 92_000, measured_at: "2026-10-02T08:00:00.000Z" },
  { model_key: "luna", context_window: 258_000, input_tokens: -1, measured_at: "2026-10-02T08:00:00.000Z" },
  { model_key: "luna", context_window: 258_000, input_tokens: null, measured_at: "2026-10-02T08:00:00.000Z" },
])("rejects invalid or mismatched statistics %#", async value => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(value)));
  await expect(loadContextWindow("luna", null, new AbortController().signal)).rejects.toThrow();
});

it("does not turn an unavailable endpoint into zero usage", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 503 })));
  await expect(loadContextWindow("luna", null, new AbortController().signal)).rejects.toThrow("CONTEXT_WINDOW_UNAVAILABLE");
});
