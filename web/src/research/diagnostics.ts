import { coreFetch } from "../auth/coreFetch";

type SourcePosition = { offset: number; line: number; column: number };
export type FormulaDiagnostic = {
  code: string;
  message: string;
  severity: "error";
  range: { start: SourcePosition; end: SourcePosition };
};
type FormulaDiagnostics = { valid: boolean; diagnostics: FormulaDiagnostic[] };
export type DiagnosticState =
  | { kind: "idle"; result: null }
  | { kind: "checking"; result: null }
  | { kind: "complete"; result: FormulaDiagnostics }
  | { kind: "unavailable"; result: null };

export function createDiagnosticsScheduler(
  request: typeof fetch = coreFetch,
  delayMilliseconds = 300,
) {
  let generation = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let controller: AbortController | null = null;

  function diagnose(source: string, publish: (state: DiagnosticState) => void): void {
    generation += 1;
    const selectedGeneration = generation;
    if (timer !== null) clearTimeout(timer);
    controller?.abort();
    if (source.trim() === "") {
      publish({ kind: "idle", result: null });
      return;
    }
    publish({ kind: "checking", result: null });
    timer = setTimeout(async () => {
      controller = new AbortController();
      try {
        const response = await request("/api/alpha/diagnostics", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source }),
          signal: controller.signal,
        });
        if (!response.ok) throw new Error("Formula diagnostics unavailable");
        const result = (await response.json()) as FormulaDiagnostics;
        if (selectedGeneration === generation) publish({ kind: "complete", result });
      } catch (reason: unknown) {
        if (selectedGeneration !== generation) return;
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        publish({ kind: "unavailable", result: null });
      }
    }, delayMilliseconds);
  }

  function dispose(): void {
    generation += 1;
    if (timer !== null) clearTimeout(timer);
    controller?.abort();
  }

  return { diagnose, dispose };
}
