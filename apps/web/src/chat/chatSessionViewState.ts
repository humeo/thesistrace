import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import type { ChatAnswer } from "@thesistrace/contracts/chat-answer";
import type { TimelineTurn } from "./chatProtocol";
import type { AgentSessionSummary } from "./sessionHistory";
import type { StagedInput } from "./stagedInputStore";
import type { AgentSessionPreference } from "./sessionPreference";

export type ChatSessionViewState = {
  messageDraft: string;
  answerDraft: (ChatAnswer & { interruptId: string }) | null;
  requestedPreference: AgentSessionPreference | null;
  readingPosition: { top: number; height: number } | null;
  stageWrite?: { draft: string; result: Promise<StagedInput> } | null;
  pendingCommand?: Readonly<{
    clearAnswer: boolean;
    commandId: string;
    draft: string | null;
    item: StagedInput | null;
  }> | null;
  snapshot?: {
    session: AgentSessionSummary | null;
    turns: readonly TimelineTurn[];
    nextCursor: string | null;
    initialized: boolean;
  };
};

/** UI edits live for this Researcher's workspace; server snapshots expire normally. */
export function useChatSessionViewState(threadId: string | null): ChatSessionViewState {
  const client = useQueryClient();
  const [view] = useState<ChatSessionViewState>(() => ({
    messageDraft: "", answerDraft: null, requestedPreference: null, readingPosition: null,
    ...client.getQueryData<Omit<ChatSessionViewState, "snapshot">>(["chat-view", threadId]),
    snapshot: client.getQueryData<ChatSessionViewState["snapshot"]>(["chat-snapshot", threadId]),
  }));
  useEffect(() => {
    // Keep unsent input independently of the bounded server-data cache.
    client.setQueryDefaults(["chat-view"], { gcTime: Infinity });
    return () => {
      if (threadId === null) return;
      const { snapshot, ...edits } = view;
      client.setQueryData(["chat-view", threadId], edits);
      if (snapshot) client.setQueryData(["chat-snapshot", threadId], snapshot);
    };
  }, [client, threadId, view]);
  return view;
}
