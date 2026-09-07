import { loadAgentSession, type AgentSessionSummary } from "./sessionHistory";

const SELECTED_SESSION_POLL_MS = 2_000;

/** Observe one mounted Chat, not its independent Core research resources. */
export async function watchSelectedSession(options: Readonly<{
  isStreaming: () => boolean;
  signal: AbortSignal;
  synchronize: (session: AgentSessionSummary) => Promise<void>;
  threadId: string;
}>): Promise<void> {
  let observed: AgentSessionSummary | undefined;
  while (!options.signal.aborted) {
    if (!options.isStreaming() && document.visibilityState !== "hidden") {
      // loadAgentSession owns the five-second request deadline and exact
      // identity validation. A failure stops observation; it is not a retry
      // of a model invocation or of the last user message.
      let session: AgentSessionSummary | undefined;
      try {
        session = await loadAgentSession(options.threadId, options.signal);
      } catch (error) {
        // A newly accepted local stream owns its connection state. A failed
        // earlier metadata probe must not replace it with "disconnected".
        if (options.signal.aborted || !options.isStreaming()) throw error;
      }
      if (options.signal.aborted) return;
      if (session !== undefined && !options.isStreaming() && (
        observed === undefined
        || observed.activity_at !== session.activity_at
        || observed.current_turn?.id !== session.current_turn?.id
        || observed.current_turn?.status !== session.current_turn?.status
      )) {
        observed = session;
        await options.synchronize(session);
      }
    }
    await nextSelectedSessionProbe(options.signal);
  }
}

function nextSelectedSessionProbe(signal: AbortSignal): Promise<void> {
  if (signal.aborted) return Promise.resolve();
  return new Promise((resolve) => {
    const finish = () => {
      clearTimeout(timer);
      signal.removeEventListener("abort", finish);
      document.removeEventListener("visibilitychange", visible);
      resolve();
    };
    const visible = () => {
      if (document.visibilityState !== "hidden") finish();
    };
    const timer = setTimeout(finish, SELECTED_SESSION_POLL_MS);
    signal.addEventListener("abort", finish, { once: true });
    document.addEventListener("visibilitychange", visible);
  });
}
