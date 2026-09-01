import { createAnthropic } from "@ai-sdk/anthropic";
import { createGoogleGenerativeAI } from "@ai-sdk/google";
import { createOpenAI } from "@ai-sdk/openai";
import type {
  LanguageModelV3,
  SharedV3ProviderOptions,
} from "@ai-sdk/provider";

import { AgentConfigurationError } from "./failure.js";
import type {
  ModelRegistry,
  ReasoningEffort,
  RegisteredModel,
} from "./model-registry.js";
import {
  SCRIPTED_FAILURE_MODEL_ID,
  ScriptedLanguageModel,
} from "./scripted-language-model.js";
import { GuardedLanguageModel, type RunModelObservation } from "./guarded-language-model.js";

export type ResolvedModelSelection = Readonly<{
  effort: ReasoningEffort;
  languageModel: LanguageModelV3;
  model: RegisteredModel;
  providerOptions: SharedV3ProviderOptions;
}>;

export class RegisteredModelRuntime {
  private readonly languageModels: ReadonlyMap<string, LanguageModelV3>;

  constructor(private readonly registry: ModelRegistry) {
    this.languageModels = new Map(
      registry.models
        .filter((model) => model.enabled)
        .map((model) => [model.key, createLanguageModel(model)] as const),
    );
  }

  resolve(
    modelKey: string,
    effort: ReasoningEffort,
    observation?: RunModelObservation,
  ): ResolvedModelSelection {
    const model = this.registry.models.find(
      (candidate) => candidate.enabled && candidate.key === modelKey,
    );
    const languageModel = this.languageModels.get(modelKey);
    if (
      model === undefined
      || languageModel === undefined
      || !model.reasoningEfforts.includes(effort)
    ) {
      throw new AgentConfigurationError();
    }
    return {
      effort,
      languageModel: observation === undefined
        ? languageModel
        : new GuardedLanguageModel(languageModel, observation),
      model,
      providerOptions: providerOptionsFor(model, effort),
    };
  }
}

function createLanguageModel(model: RegisteredModel): LanguageModelV3 {
  if (model.credential === null) throw new AgentConfigurationError();
  switch (model.providerAdapter) {
    case "anthropic":
      return createAnthropic({ apiKey: model.credential })(model.providerModelId);
    case "google":
      return createGoogleGenerativeAI({ apiKey: model.credential })(model.providerModelId);
    case "openai":
      return createOpenAI({ apiKey: model.credential })(model.providerModelId);
    case "scripted":
      return new ScriptedLanguageModel(
        model.providerModelId,
        model.providerModelId === SCRIPTED_FAILURE_MODEL_ID
          ? "throw-before-stream"
          : "reply",
      );
  }
}

function providerOptionsFor(
  model: RegisteredModel,
  effort: ReasoningEffort,
): SharedV3ProviderOptions {
  switch (model.providerAdapter) {
    case "anthropic":
      return effort === "none"
        ? { anthropic: { thinking: { type: "disabled" } } }
        : {
            anthropic: {
              effort,
              thinking: { type: "adaptive" },
            },
          };
    case "google":
      return effort === "none"
        ? { google: { thinkingConfig: { thinkingBudget: 0 } } }
        : { google: { thinkingConfig: { thinkingLevel: effort } } };
    case "openai":
      // Mastra owns conversation history. Replay native encrypted reasoning
      // instead of depending on provider-side item retention between steps.
      return { openai: { reasoningEffort: effort, serviceTier: "default", store: false } };
    case "scripted":
      return {};
  }
}
