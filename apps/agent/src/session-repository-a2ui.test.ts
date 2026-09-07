import type { Message } from "@ag-ui/core";
import { describe, expect, it } from "vitest";

import {
  RESEARCH_A2UI_ACTIVITY_TYPE,
  safeResearchA2UIErrorContent,
} from "@thesistrace/contracts/research-a2ui";
import {
  TranscriptConflictError,
  mergeA2UIActivities,
} from "./session-repository.js";

describe("mergeA2UIActivities", () => {
  it("places owned surfaces after the owner's Tool results in durable order", () => {
    const messages: Message[] = [{
      content: "",
      id: "assistant-owner",
      role: "assistant",
      toolCalls: [{
        function: { arguments: "{}", name: "render_a2ui" },
        id: "render-call",
        type: "function",
      }],
    }, {
      content: "completed",
      id: "tool-result",
      role: "tool",
      toolCallId: "render-call",
    }, {
      content: "Explanation",
      id: "assistant-text",
      role: "assistant",
    }];
    const activity = activityMessage("owned-surface");

    expect(mergeA2UIActivities(messages, [{
      message: activity,
      ownerMessageId: "assistant-owner",
    }]).map((message) => message.id)).toEqual([
      "assistant-owner",
      "tool-result",
      "owned-surface",
      "assistant-text",
    ]);
  });

  it("fails closed instead of replaying a surface without its owning Message", () => {
    expect(() => mergeA2UIActivities([], [{
      message: activityMessage("orphan-surface"),
      ownerMessageId: "missing-owner",
    }])).toThrow(TranscriptConflictError);
  });
});

function activityMessage(id: string): Extract<Message, { role: "activity" }> {
  return {
    activityType: RESEARCH_A2UI_ACTIVITY_TYPE,
    content: safeResearchA2UIErrorContent(),
    id,
    role: "activity",
  };
}
