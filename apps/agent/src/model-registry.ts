import { z } from "zod";

import { AgentConfigurationError } from "./failure.js";

export const reasoningEfforts = [
  "none",
  "minimal",
  "low",
  "medium",
  "high",
  "xhigh",
  "max",
] as const;

const providerAdapters = ["anthropic", "google", "openai", "scripted"] as const;
const providerReasoningEfforts = {
  anthropic: new Set<ReasoningEffort>(["none", "low", "medium", "high", "xhigh"]),
  google: new Set<ReasoningEffort>(["none", "minimal", "low", "medium", "high"]),
  openai: new Set<ReasoningEffort>(reasoningEfforts),
  scripted: new Set<ReasoningEffort>(reasoningEfforts),
} as const;
const providerSecretEnvironment = {
  anthropic: "THESISTRACE_AGENT_ANTHROPIC_API_KEY",
  google: "THESISTRACE_AGENT_GOOGLE_API_KEY",
  openai: "THESISTRACE_AGENT_OPENAI_API_KEY",
  scripted: "THESISTRACE_AGENT_SCRIPTED_MODEL_SECRET",
} as const satisfies Record<(typeof providerAdapters)[number], string>;
const reasoningEffortSchema = z.enum(reasoningEfforts);
// USD per million tokens, stored internally as integer nanodollars per token.
const tokenPriceSchema = z.number().nonnegative().finite()
  .refine((value) => Number(value.toFixed(3)) === value && Number.isSafeInteger(Math.round(value * 1000)));
const modelPricingSchema = z.object({
  input: tokenPriceSchema,
  cache_read: tokenPriceSchema,
  cache_write: tokenPriceSchema,
  output: tokenPriceSchema,
}).strict();
const registryModelSchema = z
  .object({
    context_window: z.number().int().min(16_384),
    max_output_tokens: z.number().int().positive(),
    pricing_usd_per_million_tokens: modelPricingSchema,
    default_reasoning_effort: reasoningEffortSchema,
    display_name: z.string().min(1).max(80).refine(isCanonicalText),
    enabled: z.boolean(),
    key: z.string().regex(/^[a-z0-9][a-z0-9._-]{0,63}$/),
    provider_adapter: z.enum(providerAdapters),
    provider_model_id: z.string().refine(isProviderModelId),
    reasoning_efforts: z.array(reasoningEffortSchema).min(1).max(reasoningEfforts.length),
    secret_env: z.string().regex(/^[A-Z][A-Z0-9_]{0,127}$/),
  })
  .strict();
const registrySchema = z
  .object({
    min_compaction_context_window: z.number().int().positive(),
    default_model_key: z.string().regex(/^[a-z0-9][a-z0-9._-]{0,63}$/),
    models: z.array(registryModelSchema).min(1).max(64),
  })
  .strict();

export type ReasoningEffort = z.infer<typeof reasoningEffortSchema>;
type ProviderAdapter = (typeof providerAdapters)[number];
type SafeModel = Readonly<{
  default_reasoning_effort: ReasoningEffort;
  display_name: string;
  key: string;
  reasoning_efforts: readonly ReasoningEffort[];
}>;
export type SafeModelCatalog = Readonly<{
  default_model_key: string;
  models: readonly SafeModel[];
}>;
export type RegisteredModel = Readonly<{
  pricing: Readonly<{ input: number; cacheRead: number; cacheWrite: number; output: number }>;
  contextWindow: number;
  maxOutputTokens: number;
  credential: string | null;
  defaultReasoningEffort: ReasoningEffort;
  displayName: string;
  enabled: boolean;
  key: string;
  providerAdapter: ProviderAdapter;
  providerModelId: string;
  reasoningEfforts: readonly ReasoningEffort[];
}>;
export type ModelRegistry = Readonly<{
  minCompactionContextWindow: number;
  defaultModelKey: string;
  models: readonly RegisteredModel[];
  safeCatalog: SafeModelCatalog;
}>;

type Environment = Readonly<Record<string, string | undefined>>;

export function readModelRegistry(
  encoded: string,
  environment: Environment,
): ModelRegistry {
  let value: unknown;
  try {
    value = JSON.parse(encoded);
  } catch {
    throw invalidConfiguration();
  }
  const parsed = registrySchema.safeParse(value);
  if (!parsed.success) throw invalidConfiguration();

  const keys = new Set<string>();
  const displays = new Set<string>();
  const models: RegisteredModel[] = [];
  for (const model of parsed.data.models) {
    const displayIdentity = model.display_name.normalize("NFKC").toLocaleLowerCase("en-US");
    if (keys.has(model.key) || displays.has(displayIdentity)) {
      throw invalidConfiguration();
    }
    keys.add(model.key);
    displays.add(displayIdentity);

    if (new Set(model.reasoning_efforts).size !== model.reasoning_efforts.length) {
      throw invalidConfiguration();
    }
    if (!model.reasoning_efforts.includes(model.default_reasoning_effort)) {
      throw invalidConfiguration();
    }
    if (
      model.reasoning_efforts.some(
        (effort) => !providerReasoningEfforts[model.provider_adapter].has(effort),
      )
    ) {
      throw invalidConfiguration();
    }
    if (model.secret_env !== providerSecretEnvironment[model.provider_adapter]) {
      throw invalidConfiguration();
    }
    const credential = environment[model.secret_env];
    if (model.enabled && (credential === undefined || credential.trim() === "")) {
      throw invalidConfiguration();
    }
    models.push({
      pricing: {
        input: Math.round(model.pricing_usd_per_million_tokens.input * 1000),
        cacheRead: Math.round(model.pricing_usd_per_million_tokens.cache_read * 1000),
        cacheWrite: Math.round(model.pricing_usd_per_million_tokens.cache_write * 1000),
        output: Math.round(model.pricing_usd_per_million_tokens.output * 1000),
      },
      contextWindow: model.context_window,
      maxOutputTokens: model.max_output_tokens,
      credential: model.enabled ? credential ?? null : null,
      defaultReasoningEffort: model.default_reasoning_effort,
      displayName: model.display_name,
      enabled: model.enabled,
      key: model.key,
      providerAdapter: model.provider_adapter,
      providerModelId: model.provider_model_id,
      reasoningEfforts: [...model.reasoning_efforts],
    });
  }

  const defaultModel = models.find((model) => model.key === parsed.data.default_model_key);
  if (defaultModel === undefined || !defaultModel.enabled) {
    throw invalidConfiguration();
  }
  const enabledModels = models.filter((model) => model.enabled);
  if (enabledModels.length === 0) throw invalidConfiguration();

  return {
    minCompactionContextWindow: parsed.data.min_compaction_context_window,
    defaultModelKey: defaultModel.key,
    models,
    safeCatalog: {
      default_model_key: defaultModel.key,
      models: enabledModels.map((model) => ({
        default_reasoning_effort: model.defaultReasoningEffort,
        display_name: model.displayName,
        key: model.key,
        reasoning_efforts: [...model.reasoningEfforts],
      })),
    },
  };
}

function isCanonicalText(value: string): boolean {
  return value.trim() === value
    && value.length > 0
    && !/[\p{Cc}\p{Cf}\p{Cs}\p{Zl}\p{Zp}]/u.test(value);
}

export function isProviderModelId(value: unknown): value is string {
  return typeof value === "string" && value.length <= 200
    && /^[A-Za-z0-9][A-Za-z0-9._:-]*(?:\/[A-Za-z0-9][A-Za-z0-9._:-]*)*$/.test(value);
}

function invalidConfiguration(): AgentConfigurationError {
  return new AgentConfigurationError();
}
