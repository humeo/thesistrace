import { describe, expect, it } from "vitest";

import {
  AgentSessionPreferenceInvalidError,
  decodeAgentSessionPreference,
} from "./sessionPreference";

describe("Agent Session preference", () => {
  it("accepts only the closed browser-safe preference shape", () => {
    expect(decodeAgentSessionPreference({
      model_key: "research-primary",
      reasoning_effort: "high",
    })).toEqual({
      model_key: "research-primary",
      reasoning_effort: "high",
    });
    expect(() => decodeAgentSessionPreference({
      model_key: "research-primary",
      provider_model_id: "private-provider-id",
      reasoning_effort: "high",
    })).toThrow(AgentSessionPreferenceInvalidError);
    expect(() => decodeAgentSessionPreference({
      model_key: "research-primary",
      reasoning_effort: "provider-specific",
    })).toThrow(AgentSessionPreferenceInvalidError);
  });
});
