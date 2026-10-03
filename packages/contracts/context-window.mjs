import { z } from "zod";

export const contextWindowSnapshotSchema = z.object({
  model_key: z.string().regex(/^[a-z0-9][a-z0-9._-]{0,63}$/),
  context_window: z.number().int().positive().safe(),
  input_tokens: z.number().int().nonnegative().safe().nullable(),
  measured_at: z.string().datetime().nullable(),
}).strict().refine(value => (value.input_tokens === null) === (value.measured_at === null));
