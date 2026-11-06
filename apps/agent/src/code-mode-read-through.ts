import { CODE_MODE_READ_TOOLS } from "./code-mode-activity.js";

type ReadCall = { name: string; input: Record<string, unknown> };
export type CodeModeReadThrough = Readonly<{ kind: "call" | "batch"; calls: ReadCall[] }>;
const reads = new Set<string>(CODE_MODE_READ_TOOLS);

export function codeModeReadThroughBatch(calls: readonly ReadCall[]): string {
  return `const __readThroughs = ${JSON.stringify(calls)};\nreturn await Promise.all([${calls.map(call => `external_${call.name}(${JSON.stringify(call.input)})`).join(",")}]);`;
}

/** Prove only unchanged literal reads; arbitrary programs provide no oracle evidence. */
export function readCodeModeReadThrough(input: unknown): CodeModeReadThrough | undefined {
  if (!input || typeof input !== "object" || !("code" in input) || typeof input.code !== "string"
    || Buffer.byteLength(input.code, "utf8") > 64 * 1024) return undefined;
  const single = /^\s*return\s+await\s+external_([a-z_]+)\((.*)\)\s*;?\s*$/s.exec(input.code);
  try {
    if (single && reads.has(single[1]!)) {
      const args: unknown = JSON.parse(single[2]!);
      return isRecord(args) ? { kind: "call", calls: [{ name: single[1]!, input: args }] } : undefined;
    }
    const batch = /^const __readThroughs = (.+);\n/.exec(input.code);
    if (!batch) return undefined;
    const calls: unknown = JSON.parse(batch[1]!);
    if (!Array.isArray(calls) || !calls.length || !calls.every(call => isRecord(call)
      && typeof call.name === "string" && reads.has(call.name) && isRecord(call.input))) return undefined;
    // Metadata alone cannot prove a call happened. Verify the complete program.
    return codeModeReadThroughBatch(calls) === input.code ? { kind: "batch", calls } : undefined;
  } catch { return undefined; }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
