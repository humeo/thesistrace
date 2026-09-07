import type { LanguageModelV3, LanguageModelV3CallOptions } from "@ai-sdk/provider";

/** Run-scoped main-model boundary; auxiliary models retain their own guarded path. */
export class ContextLanguageModel implements LanguageModelV3 {
  readonly specificationVersion = "v3" as const;
  constructor(private readonly delegate: LanguageModelV3,
    private readonly prepare: (request: LanguageModelV3CallOptions) => Promise<LanguageModelV3CallOptions>) {}
  get modelId() { return this.delegate.modelId; }
  get provider() { return this.delegate.provider; }
  get supportedUrls() { return this.delegate.supportedUrls; }
  async doGenerate(request: LanguageModelV3CallOptions) {
    return this.delegate.doGenerate(await this.prepare(request));
  }
  async doStream(request: LanguageModelV3CallOptions) {
    return this.delegate.doStream(await this.prepare(request));
  }
}
