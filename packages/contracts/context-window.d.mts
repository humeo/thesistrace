import type { ZodType } from "zod";

export type ContextWindowSnapshot = Readonly<{
  model_key: string;
  context_window: number;
  input_tokens: number | null;
  measured_at: string | null;
}>;
export const contextWindowSnapshotSchema: ZodType<ContextWindowSnapshot>;
