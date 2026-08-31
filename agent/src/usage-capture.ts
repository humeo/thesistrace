import type { LanguageModelV3Usage } from "@ai-sdk/provider";

export class RunUsageCapture {
  private usage: PersistedTokenUsage | undefined;
  private startedSteps = 0;
  private reportedSteps = 0;
  private unreported = false;

  beginStep(): void {
    this.startedSteps++;
  }

  capture(usage: LanguageModelV3Usage): void {
    try {
      const next = normalizeTokenUsage(usage);
      this.usage = this.usage === undefined ? next : {
        reported: true,
        inputTokens: addCounters(this.usage.inputTokens, next.inputTokens),
        outputTokens: addCounters(this.usage.outputTokens, next.outputTokens),
      };
      this.reportedSteps++;
    } catch {
      // Accounting is non-critical. A malformed usage object is unreported,
      // never invented zero usage and never a failed primary Agent run.
      this.usage = undefined;
      this.unreported = true;
    }
  }

  value(): PersistedTokenUsage | undefined {
    return this.unreported || this.startedSteps > this.reportedSteps || this.usage === undefined
      ? undefined : structuredClone(this.usage);
  }
}

/** Unknown accounting fields stay undefined at the framework boundary. */
export function frameworkTokenUsage(value: unknown): LanguageModelV3Usage {
  const record = (part: unknown): Record<string, unknown> => part !== null && typeof part === "object" ? part as Record<string, unknown> : {};
  const usage = record(value);
  const input = record(usage.inputTokens);
  const output = record(usage.outputTokens);
  const count = (part: unknown) => typeof part === "number" && Number.isSafeInteger(part) && part >= 0 ? part : undefined;
  return {
    inputTokens: { total: count(input.total), noCache: count(input.noCache), cacheRead: count(input.cacheRead), cacheWrite: count(input.cacheWrite) },
    outputTokens: { total: count(output.total), text: count(output.text), reasoning: count(output.reasoning) },
  };
}

export type PersistedTokenUsage = Readonly<{
  reported: true;
  inputTokens: Readonly<{
    cacheRead: number | null;
    cacheWrite: number | null;
    noCache: number | null;
    total: number | null;
  }>;
  outputTokens: Readonly<{
    reasoning: number | null;
    text: number | null;
    total: number | null;
  }>;
}>;

export function normalizeTokenUsage(usage: LanguageModelV3Usage): PersistedTokenUsage {
  return {
    reported: true,
    inputTokens: {
      cacheRead: tokenCount(usage.inputTokens.cacheRead),
      cacheWrite: tokenCount(usage.inputTokens.cacheWrite),
      noCache: tokenCount(usage.inputTokens.noCache),
      total: tokenCount(usage.inputTokens.total),
    },
    outputTokens: {
      reasoning: tokenCount(usage.outputTokens.reasoning),
      text: tokenCount(usage.outputTokens.text),
      total: tokenCount(usage.outputTokens.total),
    },
  };
}

function addCounters<T extends Record<string, number | null>>(left: T, right: T): T {
  return Object.fromEntries(Object.keys(left).map((key) => {
    const a = left[key];
    const b = right[key];
    const sum = a === null || b === null ? null : a! + b!;
    return [key, sum !== null && Number.isSafeInteger(sum) ? sum : null];
  })) as T;
}

function tokenCount(value: number | undefined): number | null {
  return Number.isSafeInteger(value) && (value ?? -1) >= 0 ? value ?? null : null;
}
