import type { HttpAgentFetchFn } from "@ag-ui/client";
import { isAgentFailureCode, runFailureEvent, type AgentFailureCode } from "../../../contracts/agent-failure.mjs";

const REQUEST_HEADERS_TIMEOUT_MS = 5_000;
const MAX_ERROR_BYTES = 4_096;

/** Public AG-UI HttpAgent fetch seam; no second stream protocol or retry loop. */
export function createAgentFetch(fetch: HttpAgentFetchFn): HttpAgentFetchFn {
  return async (url, init) => {
    const controller = new AbortController();
    const signal = init.signal == null ? controller.signal : AbortSignal.any([init.signal, controller.signal]);
    let deadline!: (value: Response) => void;
    const timeout = new Promise<Response>((resolve) => { deadline = resolve; });
    const timer = setTimeout(() => {
      controller.abort();
      deadline(terminalResponse("AGENT_UNAVAILABLE"));
    }, REQUEST_HEADERS_TIMEOUT_MS);
    const request = (async () => {
      try {
        const response = await fetch(url, { ...init, signal });
        if (response.ok && response.headers.get("content-type")?.includes("text/event-stream")) return response;
        if (response.status === 401 || response.status >= 500) {
          void response.body?.cancel().catch(() => undefined);
          return terminalResponse(response.status === 401 ? "AUTHENTICATION_REQUIRED" : "AGENT_UNAVAILABLE");
        }
        return terminalResponse(await readFailureCode(response, signal));
      } catch {
        return terminalResponse("AGENT_UNAVAILABLE");
      }
    })();
    try { return await Promise.race([request, timeout]); }
    finally { clearTimeout(timer); }
  };
}

async function readFailureCode(response: Response, signal: AbortSignal): Promise<AgentFailureCode> {
  const reader = response.body?.getReader();
  if (reader === undefined) return "INTERNAL_FAILURE";
  const cancel = () => { void reader.cancel().catch(() => undefined); };
  signal.addEventListener("abort", cancel, { once: true });
  if (signal.aborted) cancel();
  try {
    const chunks: Uint8Array[] = [];
    let bytes = 0;
    for (;;) {
      const part = await reader.read();
      if (part.done) break;
      bytes += part.value.byteLength;
      if (bytes > MAX_ERROR_BYTES) return "INTERNAL_FAILURE";
      chunks.push(part.value);
    }
    const combined = new Uint8Array(bytes);
    let offset = 0;
    for (const chunk of chunks) { combined.set(chunk, offset); offset += chunk.byteLength; }
    const value: unknown = JSON.parse(new TextDecoder().decode(combined));
    return value !== null && typeof value === "object" && "code" in value && isAgentFailureCode(value.code)
      ? value.code : "INTERNAL_FAILURE";
  } finally { signal.removeEventListener("abort", cancel); cancel(); }
}

function terminalResponse(code: AgentFailureCode): Response {
  return new Response(`data: ${JSON.stringify(runFailureEvent(code))}\n\n`, {
    headers: { "content-type": "text/event-stream", "cache-control": "no-store" },
  });
}
