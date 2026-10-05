import { StreamErrorRetryProcessor, type ProcessAPIErrorArgs } from "@mastra/core/processors";
import { transientProviderFailure } from "./run-failure.js";

export const PROVIDER_MAX_RETRIES = 2;

export function providerRetryProcessor(onRetry: (args: ProcessAPIErrorArgs) => Promise<void>) {
  const retry = new StreamErrorRetryProcessor({
    maxRetries: PROVIDER_MAX_RETRIES,
    delayMs: ({ retryCount }) => 1000 * 2 ** retryCount,
    matchers: [transientProviderFailure],
  });
  return {
    id: "provider-retry",
    processAPIError: async (args: ProcessAPIErrorArgs) => {
      if (args.abortSignal?.aborted || !transientProviderFailure(args.error)) return;
      // The framework shares retryCount with context recovery; provider retries
      // have their own allowance, reset only after a successful model step.
      const retryCount = args.state.stepNumber === args.stepNumber ? Number(args.state.attempts) : 0;
      const result = await retry.processAPIError({ ...args, retryCount });
      if (result?.retry && !args.abortSignal?.aborted) {
        await onRetry(args);
        args.state.stepNumber = args.stepNumber;
        args.state.attempts = retryCount + 1;
      }
      return result;
    },
  };
}
