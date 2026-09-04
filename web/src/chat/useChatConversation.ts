import { HttpAgent, type AgentSubscriber } from "@ag-ui/client";
import { useCallback, useEffect, useRef, useState, type SetStateAction } from "react";

import { formatChatAnswer, isChatAnswer, type ChatAnswer } from "../../../contracts/chat-answer.mjs";

import type { AgentSessionSummary } from "./sessionHistory";
import { loadAgentSession } from "./sessionHistory";
import {
  ChatApiError,
  ChatCommandAcceptanceUnknownError,
  loadCommandReceipt,
  loadTimelinePage,
  steerChat,
  stopChat,
  type ChatCommandReceipt,
  type ChatQuestion,
  type ChatTurnStatus,
  type TimelineTurn,
} from "./chatProtocol";
import {
  deriveChatPhase,
  deriveMainAction,
  type ChatMainAction,
  type ChatPhase,
  type DraftValidity,
  type ResolvedModelSelection,
} from "./chatState";
import {
  createStagedInputChannel,
  StagedInputStore,
  StagedInputStoreError,
  type StagedInput,
  withStagedDeliveryLock,
} from "./stagedInputStore";

type LocalCommand = "none" | "opening" | "stopping" | "recovering";
type Recovery = Readonly<{
  clearAnswer: boolean;
  commandId: string;
  draft: string | null;
  item: StagedInput | null;
}>;
type TimelineLoadState = {
  generation: number;
  promise: Promise<void>;
  rerun: boolean;
};

export type ChatConversationController = Readonly<{
  action: ChatMainAction;
  answerSelections: readonly string[];
  currentTurnId: string | null;
  draft: string;
  draftBytes: number;
  editStaged: (item: StagedInput) => Promise<void>;
  error: string | null;
  errorCode: string | null;
  executeMainAction: () => Promise<void>;
  focusComposer: () => void;
  hasFirstAssistantText: boolean;
  loadOlder: () => Promise<boolean>;
  loadingOlder: boolean;
  latestTurnId: string | null;
  latestTurnStatus: ChatTurnStatus | null;
  nextCursor: string | null;
  phase: ChatPhase;
  question: ChatQuestion | null;
  queue: readonly StagedInput[];
  queueLocked: boolean;
  refresh: () => Promise<void>;
  removeStaged: (item: StagedInput) => Promise<void>;
  retryRecovery: () => Promise<void>;
  retryTimeline: () => Promise<void>;
  setAnswerSelections: (values: readonly string[]) => void;
  setDraft: (value: string) => void;
  steerStaged: (item: StagedInput) => Promise<void>;
  stopTurn: () => Promise<void>;
  statusAnnouncement: string;
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
  turns: readonly TimelineTurn[];
  timelineError: boolean;
}>;

export function useChatConversation(options: Readonly<{
  agent: HttpAgent;
  existingSession: boolean;
  initialSession?: AgentSessionSummary;
  onAccepted: () => void;
  onSessionChanged: () => void;
  onTitleMaySettle: (threadId: string) => void;
  researcherId: string;
  selection: ResolvedModelSelection | null;
  threadId: string;
  titleMaySettle: boolean;
}>): ChatConversationController {
  const [session, setSession] = useState<AgentSessionSummary | null>(
    options.existingSession ? options.initialSession ?? null : null,
  );
  const [opening, setOpening] = useState(options.existingSession && options.initialSession === undefined);
  const [localCommand, setLocalCommand] = useState<LocalCommand>("none");
  const [messageDraft, setMessageDraft] = useState("");
  const [answerDraft, setAnswerDraft] = useState<ChatAnswer & { interruptId: string } | null>(null);
  const [submittingQuestion, setSubmittingQuestion] = useState<ChatQuestion | null>(null);
  const [turns, setTurns] = useState<readonly TimelineTurn[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [latestTimelineError, setLatestTimelineError] = useState(false);
  const [olderTimelineError, setOlderTimelineError] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [queue, setQueue] = useState<readonly StagedInput[]>([]);
  const [queueLocked, setQueueLocked] = useState(false);
  const [stageWriting, setStageWriting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorCode, setErrorCode] = useState<string | null>(null);
  const [recovery, setRecovery] = useState<Recovery | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const storeRef = useRef<StagedInputStore | null>(null);
  const stagedChannelRef = useRef<ReturnType<typeof createStagedInputChannel> | null>(null);
  const callbacksRef = useRef({
    onAccepted: options.onAccepted,
    onSessionChanged: options.onSessionChanged,
    onTitleMaySettle: options.onTitleMaySettle,
    titleMaySettle: options.titleMaySettle,
  });
  const initialSessionRef = useRef(options.initialSession);
  const sessionRef = useRef(session);
  const selectionRef = useRef(options.selection);
  const queueRef = useRef(queue);
  const queueLockedRef = useRef(queueLocked);
  const stageWritingRef = useRef(false);
  const generationRef = useRef(0);
  const runInFlightRef = useRef(false);
  const stopInFlightRef = useRef(false);
  const sessionEstablishedRef = useRef(options.existingSession);
  const observedActiveTurnsRef = useRef(new Set<string>());
  const handledCompletionsRef = useRef(new Set<string>());
  const completionDeliveriesRef = useRef(new Set<string>());
  const watchedTitlesRef = useRef(new Set<string>());
  const timelineInitializedRef = useRef(false);
  const timelineLoadRef = useRef<TimelineLoadState | null>(null);
  const tabIdRef = useRef(crypto.randomUUID());
  sessionRef.current = session;
  selectionRef.current = options.selection;
  queueRef.current = queue;
  queueLockedRef.current = queueLocked;
  callbacksRef.current = {
    onAccepted: options.onAccepted,
    onSessionChanged: options.onSessionChanged,
    onTitleMaySettle: options.onTitleMaySettle,
    titleMaySettle: options.titleMaySettle,
  };

  const question = submittingQuestion ?? (session?.current_turn?.status === "waiting_for_user"
    ? session.current_turn.question
    : null);
  const currentAnswer = question !== null && answerDraft?.interruptId === question.interrupt_id
    ? answerDraft : null;
  const answerSelections = currentAnswer?.selections ?? [];
  const draft = question === null ? messageDraft : currentAnswer?.text ?? "";
  const semanticAnswer: ChatAnswer = { selections: answerSelections, text: draft };
  const draftBytes = Math.max(
    new TextEncoder().encode(draft).byteLength,
    question === null ? 0 : new TextEncoder().encode(formatChatAnswer(semanticAnswer)).byteLength,
  );
  const draftValidity: DraftValidity = draft.trim().length === 0 && (question === null || answerSelections.length === 0)
    ? "empty"
    : (question === null || isChatAnswer(semanticAnswer)) && draftBytes <= 16 * 1024 ? "valid" : "invalid";

  const setDraft = useCallback((value: SetStateAction<string>) => {
    if (question === null) {
      setMessageDraft(value);
      return;
    }
    setAnswerDraft((current) => {
      const previous = current?.interruptId === question.interrupt_id ? current : null;
      return {
        interruptId: question.interrupt_id,
        selections: previous?.selections ?? [],
        text: typeof value === "function" ? value(previous?.text ?? "") : value,
      };
    });
  }, [question?.interrupt_id]);

  const setAnswerSelections = useCallback((selections: readonly string[]) => {
    if (question === null) return;
    setAnswerDraft((current) => ({
      interruptId: question.interrupt_id,
      selections,
      text: current?.interruptId === question.interrupt_id ? current.text : "",
    }));
  }, [question?.interrupt_id]);
  const phase = deriveChatPhase({
    currentTurn: session?.current_turn ?? null,
    localCommand: localCommand === "recovering"
      ? "recovering"
      : localCommand === "stopping" ? "stopping" : "none",
    opening: opening || localCommand === "opening",
    sessionExists: session !== null || sessionEstablishedRef.current,
  });
  const derivedAction = deriveMainAction({
    canContinue: session?.current_turn === null && session.latest_turn?.status === "stopped",
    draft: draftValidity,
    phase,
    settingsValid: options.selection !== null,
  });
  const action = derivedAction.kind === "stage" && (queueLocked || stageWriting)
    ? { ...derivedAction, enabled: false }
    : derivedAction;
  const currentTurnId = session?.current_turn?.id ?? null;
  const hasFirstAssistantText = currentTurnId === null || turns.some((turn) => (
    turn.id === currentTurnId
    && turn.entries.some((entry) => entry.kind === "assistant_message"
      && entry.payload.content.trim().length > 0)
  ));

  const focusComposer = useCallback(() => {
    const generation = generationRef.current;
    window.requestAnimationFrame(() => {
      if (generationRef.current !== generation) return;
      textareaRef.current?.focus({ preventScroll: true });
    });
  }, []);

  const loadQueue = useCallback(async () => {
    const generation = generationRef.current;
    storeRef.current ??= new StagedInputStore();
    try {
      const items = await storeRef.current.list(options.researcherId, options.threadId);
      if (generationRef.current !== generation) return;
      setQueue(items);
      setQueueLocked(false);
    } catch (failure) {
      if (generationRef.current !== generation) return;
      setQueueLocked(failure instanceof StagedInputStoreError
        && failure.code === "STAGE_STORAGE_CORRUPT");
      setError("Staged inputs could not be read. Nothing was deleted; retry after storage is available.");
    }
  }, [options.researcherId, options.threadId]);

  const loadLatestTimeline = useCallback(async (signal?: AbortSignal) => {
    const generation = generationRef.current;
    const existing = timelineLoadRef.current;
    if (existing !== null && existing.generation === generation) {
      existing.rerun = true;
      await existing.promise;
      return;
    }

    const load: TimelineLoadState = {
      generation,
      promise: Promise.resolve(),
      rerun: false,
    };
    load.promise = (async () => {
      let requestSignal = signal;
      do {
        load.rerun = false;
        try {
          const page = await loadTimelinePage(options.threadId, undefined, requestSignal);
          if (generationRef.current !== generation) return;
          setTurns((current) => mergeLatestTurns(current, page.turns));
          if (!timelineInitializedRef.current) {
            timelineInitializedRef.current = true;
            setNextCursor(page.next_cursor);
          }
          setLatestTimelineError(false);
        } catch (failure) {
          if (generationRef.current !== generation) return;
          if (!(failure instanceof DOMException && failure.name === "AbortError")) {
            setLatestTimelineError(true);
          }
        }
        // A coalesced refresh belongs to the same controller generation, but
        // not necessarily to the lifecycle AbortSignal of the first request.
        requestSignal = undefined;
      } while (load.rerun && generationRef.current === generation);
    })();
    timelineLoadRef.current = load;
    try {
      await load.promise;
    } finally {
      if (timelineLoadRef.current === load) {
        timelineLoadRef.current = null;
      }
    }
  }, [options.threadId]);

  const deliverNextStaged = useCallback(async (): Promise<boolean> => {
    const generation = generationRef.current;
    if (queueLockedRef.current || runInFlightRef.current || selectionRef.current === null) return false;
    try {
      return await withStagedDeliveryLock(options.researcherId, options.threadId, async () => {
        if (
          generationRef.current !== generation
          || queueLockedRef.current
          || runInFlightRef.current
          || selectionRef.current === null
        ) return false;
        storeRef.current ??= new StagedInputStore();
        let items: readonly StagedInput[];
        try {
          items = await storeRef.current.list(options.researcherId, options.threadId);
          if (generationRef.current !== generation) return false;
          setQueue(items);
        } catch {
          if (generationRef.current !== generation) return false;
          queueLockedRef.current = true;
          setQueueLocked(true);
          setError("Staged input storage is damaged. Automatic delivery is disabled without deleting anything.");
          return false;
        }
        const head = items[0];
        if (head === undefined) return true;
        if (head.status === "submitting") {
          if ((head.leaseUntil ?? Number.POSITIVE_INFINITY) > Date.now()) return false;
          try {
            const receipt = await loadCommandReceipt(options.threadId, head.inputId);
            if (generationRef.current !== generation) return false;
            if (receipt.status === "accepted") {
              await storeRef.current.removeAccepted(head);
              await loadQueue();
              stagedChannelRef.current?.notify();
            } else if (receipt.status === "rejected") {
              await storeRef.current.release(head);
              await loadQueue();
              stagedChannelRef.current?.notify();
            } else {
              setRecovery({ clearAnswer: false, commandId: head.inputId, draft: null, item: head });
              setLocalCommand("recovering");
              setError("Acceptance is still pending. The staged input remains protected.");
            }
            return true;
          } catch (failure) {
            if (generationRef.current !== generation) return false;
            if (!(failure instanceof ChatApiError && failure.status === 404)) {
              setRecovery({ clearAnswer: false, commandId: head.inputId, draft: null, item: head });
              setLocalCommand("recovering");
              setError("The staged input receipt could not be checked. It remains protected.");
              return false;
            }
            await storeRef.current.release(head);
            stagedChannelRef.current?.notify();
          }
        }
        if (generationRef.current !== generation) return false;
        const claimedSelection = selectionRef.current;
        if (claimedSelection === null) return false;
        const claimed = await storeRef.current.claimHead(
          options.researcherId,
          options.threadId,
          head.inputId,
          tabIdRef.current,
        );
        if (claimed === null) return false;
        await loadQueue();
        await startPrompt(claimed.content, claimed.inputId, claimed, claimedSelection);
        return true;
      });
    } catch {
      if (generationRef.current !== generation) return false;
      queueLockedRef.current = true;
      setQueueLocked(true);
      setError("Staged input coordination is unavailable. Inputs remain stored and automatic delivery is disabled.");
      return false;
    }
  // startPrompt is a stable declaration backed by refs; adding it here would
  // recreate the completion observer for every transient Run state.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadQueue, options.researcherId, options.threadId]);

  const observeSession = useCallback((next: AgentSessionSummary, generation = generationRef.current) => {
    if (generationRef.current !== generation) return;
    const previous = sessionRef.current;
    const active = next.current_turn;
    if (active !== null && active.status === "running") {
      observedActiveTurnsRef.current.add(active.id);
    }
    const completed = next.current_turn === null && next.latest_turn?.status === "completed"
      ? next.latest_turn.id
      : null;
    if (
      completed !== null
      && observedActiveTurnsRef.current.has(completed)
      && !handledCompletionsRef.current.has(completed)
      && !completionDeliveriesRef.current.has(completed)
    ) {
      completionDeliveriesRef.current.add(completed);
      void deliverNextStaged().then((handled) => {
        if (handled) handledCompletionsRef.current.add(completed);
      }).finally(() => completionDeliveriesRef.current.delete(completed));
    }
    if (
      completed !== null
      && callbacksRef.current.titleMaySettle
      && !watchedTitlesRef.current.has(completed)
    ) {
      watchedTitlesRef.current.add(completed);
      callbacksRef.current.onTitleMaySettle(options.threadId);
    }
    setSession(next);
    sessionRef.current = next;
    if (
      previous !== null
      && (
        previous.current_turn?.id !== next.current_turn?.id
        || previous.current_turn?.status !== next.current_turn?.status
      )
    ) {
      callbacksRef.current.onSessionChanged();
    }
  }, [deliverNextStaged]);

  const refresh = useCallback(async () => {
    const generation = generationRef.current;
    if (!sessionEstablishedRef.current && !options.existingSession) return;
    try {
      const next = await loadAgentSession(options.threadId);
      await loadLatestTimeline();
      if (generationRef.current !== generation) return;
      observeSession(next, generation);
      setOpening(false);
    } catch (failure) {
      if (failure instanceof DOMException && failure.name === "AbortError") return;
      setError("The authoritative Chat state could not be refreshed.");
    }
  }, [loadLatestTimeline, observeSession, options.existingSession, options.threadId]);

  async function settleAcceptedInput(
    commandId: string,
    item: StagedInput | null,
    acceptedDraft: string | null,
    clearAnswer = false,
    generation = generationRef.current,
  ): Promise<void> {
    if (generationRef.current !== generation) return;
    if (item !== null) {
      storeRef.current ??= new StagedInputStore();
      await storeRef.current.removeAccepted(item);
      await loadQueue();
      if (generationRef.current !== generation) return;
      stagedChannelRef.current?.notify();
    }
    if (acceptedDraft !== null && !clearAnswer) {
      setMessageDraft((current) => current === acceptedDraft ? "" : current);
    }
    if (clearAnswer) {
      setAnswerDraft(null);
      setSubmittingQuestion(null);
    }
    setRecovery((current) => current?.commandId === commandId ? null : current);
    setLocalCommand("none");
    sessionEstablishedRef.current = true;
    callbacksRef.current.onAccepted();
    callbacksRef.current.onSessionChanged();
    await refresh();
  }

  async function reconcileCommand(
    target: Recovery,
    generation = generationRef.current,
    absenceIsRejection = false,
  ): Promise<ChatCommandReceipt | null> {
    try {
      const receipt = await loadCommandReceipt(options.threadId, target.commandId);
      if (generationRef.current !== generation) return null;
      if (receipt.status === "pending") {
        setRecovery(target);
        setLocalCommand("recovering");
        return receipt;
      }
      if (receipt.status === "accepted") {
        await settleAcceptedInput(target.commandId, target.item, target.draft, target.clearAnswer, generation);
        return receipt;
      }
      if (target.item !== null) {
        storeRef.current ??= new StagedInputStore();
        await storeRef.current.release(target.item);
        await loadQueue();
        stagedChannelRef.current?.notify();
      }
      if (target.draft !== null && !target.clearAnswer) setMessageDraft(target.draft);
      if (target.clearAnswer) setSubmittingQuestion(null);
      setRecovery(null);
      setLocalCommand("none");
      setError(commandErrorCopy(receipt.error_code));
      return receipt;
    } catch (failure) {
      if (generationRef.current !== generation) return null;
      if (absenceIsRejection && failure instanceof ChatApiError && failure.status === 404) {
        if (target.item !== null) {
          storeRef.current ??= new StagedInputStore();
          await storeRef.current.release(target.item).catch(() => undefined);
          await loadQueue();
          stagedChannelRef.current?.notify();
        }
        if (target.draft !== null && !target.clearAnswer) setMessageDraft(target.draft);
        if (target.clearAnswer) setSubmittingQuestion(null);
        setRecovery(null);
        setLocalCommand("none");
        setError("The command was rejected before the Turn was accepted. Your input was restored.");
        return null;
      }
      setRecovery(target);
      setLocalCommand("recovering");
      setError("Acceptance is not yet known. Your input is retained until the server confirms it.");
      return null;
    }
  }

  async function settleRejectedInput(
    target: Recovery,
    rejectionCode: string,
    generation = generationRef.current,
  ): Promise<void> {
    if (generationRef.current !== generation) return;
    if (target.item !== null) {
      storeRef.current ??= new StagedInputStore();
      await storeRef.current.release(target.item).catch(() => undefined);
      await loadQueue();
      stagedChannelRef.current?.notify();
    }
    if (target.draft !== null && !target.clearAnswer) setMessageDraft(target.draft);
    if (target.clearAnswer) setSubmittingQuestion(null);
    setRecovery(null);
    setLocalCommand("none");
    setErrorCode(rejectionCode);
    setError(rejectedRunErrorCopy(rejectionCode));
    if (rejectionCode === "CHAT_SESSION_NOT_FOUND") {
      callbacksRef.current.onSessionChanged();
    }
  }

  async function startPrompt(
    content: string,
    inputId: string,
    item: StagedInput | null,
    frozenSelection?: ResolvedModelSelection,
  ): Promise<void> {
    const generation = generationRef.current;
    const selection = frozenSelection ?? selectionRef.current;
    if (selection === null || runInFlightRef.current) {
      if (item !== null) await storeRef.current?.release(item);
      return;
    }
    const runId = crypto.randomUUID();
    const recoveryTarget = { clearAnswer: false, commandId: inputId, draft: item === null ? content : null, item };
    runInFlightRef.current = true;
    setLocalCommand("opening");
    setError(null);
    setErrorCode(null);
    options.agent.setMessages([{ content, id: inputId, role: "user" }]);
    let accepted = false;
    let authoritativeRejection = false;
    let authoritativeRejectionCode: string | null = null;
    const subscriber: AgentSubscriber = {
      onRunStartedEvent: ({ event }) => {
        if (generationRef.current !== generation || event.runId !== runId || accepted) return;
        accepted = true;
        observedActiveTurnsRef.current.add(runId);
        void settleAcceptedInput(inputId, item, item === null ? content : null, false, generation);
      },
      onRunErrorEvent: ({ event }) => {
        if (!accepted) {
          authoritativeRejection = true;
          authoritativeRejectionCode = event.code ?? "INTERNAL_FAILURE";
        }
        void loadLatestTimeline();
      },
      onRunFailed: () => { void loadLatestTimeline(); },
      onRunFinishedEvent: () => { void refresh(); },
      onTextMessageContentEvent: () => { void loadLatestTimeline(); },
      onToolCallStartEvent: () => { void loadLatestTimeline(); },
      onToolCallResultEvent: () => { void loadLatestTimeline(); },
    };
    try {
      await options.agent.runAgent({
        forwardedProps: {
          thesistrace: {
            command: "prompt",
            modelKey: selection.model.key,
            reasoningEffort: selection.reasoningEffort,
            sessionMode: sessionEstablishedRef.current ? "existing" : "new",
          },
        },
        runId,
      }, subscriber);
    } catch {
      // The receipt below, not transport success, owns input cleanup.
    } finally {
      runInFlightRef.current = false;
      if (generationRef.current !== generation) return;
      if (!accepted && authoritativeRejectionCode !== null) {
        await settleRejectedInput(recoveryTarget, authoritativeRejectionCode, generation);
      } else if (!accepted) {
        await reconcileCommand(recoveryTarget, generation, authoritativeRejection);
      }
      await refresh();
      focusComposer();
    }
  }

  async function startContinue(): Promise<void> {
    const generation = generationRef.current;
    const selection = selectionRef.current;
    if (selection === null || runInFlightRef.current) return;
    const runId = crypto.randomUUID();
    runInFlightRef.current = true;
    setLocalCommand("opening");
    setError(null);
    setErrorCode(null);
    options.agent.setMessages([]);
    let accepted = false;
    let authoritativeRejection = false;
    try {
      await options.agent.runAgent({
        forwardedProps: {
          thesistrace: {
            command: "continue",
            modelKey: selection.model.key,
            reasoningEffort: selection.reasoningEffort,
            sessionMode: "existing",
          },
        },
        runId,
      }, {
        onRunStartedEvent: ({ event }) => {
          if (generationRef.current !== generation || event.runId !== runId) return;
          accepted = true;
          observedActiveTurnsRef.current.add(runId);
          setLocalCommand("none");
          void refresh();
        },
        onRunFinishedEvent: () => { void refresh(); },
        onRunErrorEvent: () => { if (!accepted) authoritativeRejection = true; void refresh(); },
        onTextMessageContentEvent: () => { void loadLatestTimeline(); },
      });
    } catch {
      // Reconcile by command id below.
    } finally {
      runInFlightRef.current = false;
      if (generationRef.current !== generation) return;
      if (!accepted) await reconcileCommand(
        { clearAnswer: false, commandId: runId, draft: null, item: null },
        generation,
        authoritativeRejection,
      );
      await refresh();
      focusComposer();
    }
  }

  async function startAnswer(answer: ChatAnswer): Promise<void> {
    const generation = generationRef.current;
    const turn = sessionRef.current?.current_turn;
    const activeQuestion = turn?.status === "waiting_for_user" ? turn.question : null;
    if (turn === undefined || turn === null || activeQuestion === null || runInFlightRef.current) return;
    observedActiveTurnsRef.current.add(turn.id);
    const inputId = crypto.randomUUID();
    const target = { clearAnswer: true, commandId: inputId, draft: answer.text || null, item: null };
    runInFlightRef.current = true;
    setSubmittingQuestion(activeQuestion);
    setLocalCommand("opening");
    setError(null);
    options.agent.setMessages([]);
    let reconciled = false;
    const reconcileOnce = (absenceIsRejection = false) => {
      if (reconciled) return;
      reconciled = true;
      void reconcileCommand(target, generation, absenceIsRejection);
    };
    try {
      await options.agent.runAgent({
        forwardedProps: {
          thesistrace: {
            command: "answer",
            inputId,
            interruptId: activeQuestion.interrupt_id,
          },
        },
        resume: [{
          interruptId: activeQuestion.interrupt_id,
          payload: answer,
          status: "resolved",
        }],
        runId: turn.id,
      }, {
        onRunStartedEvent: () => { reconcileOnce(); },
        onRunFinishedEvent: () => { reconcileOnce(true); void refresh(); },
        onRunErrorEvent: () => { reconcileOnce(true); void refresh(); },
        onTextMessageContentEvent: () => { reconcileOnce(); void loadLatestTimeline(); },
        onToolCallStartEvent: () => { reconcileOnce(); void loadLatestTimeline(); },
      });
    } catch {
      // Reconcile below.
    } finally {
      runInFlightRef.current = false;
      if (generationRef.current !== generation) return;
      if (!reconciled) await reconcileCommand(target, generation);
      await refresh();
      focusComposer();
    }
  }

  const stopTurn = useCallback(async () => {
    const turn = sessionRef.current?.current_turn;
    if (!turn || !["running", "waiting_for_user"].includes(turn.status) || stopInFlightRef.current) return;
    const generation = generationRef.current;
    const commandId = crypto.randomUUID();
    stopInFlightRef.current = true;
    setLocalCommand("stopping");
    setError(null);
    setErrorCode(null);
    try {
      const receipt = await stopChat(options.threadId, { commandId, expectedTurnId: turn.id });
      if (generationRef.current !== generation) return;
      if (receipt.status === "pending") {
        setRecovery({ clearAnswer: false, commandId, draft: null, item: null });
        setLocalCommand("recovering");
      } else if (receipt.status === "accepted") {
        setLocalCommand("none");
        await refresh();
      } else {
        setLocalCommand("none");
        setError(commandErrorCopy(receipt.error_code));
      }
    } catch (failure) {
      if (generationRef.current !== generation) return;
      if (failure instanceof ChatCommandAcceptanceUnknownError) {
        setRecovery({ clearAnswer: false, commandId, draft: null, item: null });
        setLocalCommand("recovering");
      } else {
        setLocalCommand("none");
        setError(apiErrorCopy(failure));
      }
    } finally {
      if (generationRef.current === generation) {
        stopInFlightRef.current = false;
        focusComposer();
      }
    }
  }, [focusComposer, options.threadId, refresh]);

  const executeMainAction = useCallback(async () => {
    if (!action.enabled) return;
    if (action.kind === "send") {
      const content = draft;
      await startPrompt(content, crypto.randomUUID(), null);
      return;
    }
    if (action.kind === "stage") {
      if (stageWritingRef.current) return;
      const acceptedDraft = draft;
      const generation = generationRef.current;
      stageWritingRef.current = true;
      setStageWriting(true);
      storeRef.current ??= new StagedInputStore();
      try {
        await storeRef.current.stage(options.researcherId, options.threadId, acceptedDraft);
        if (generationRef.current !== generation) return;
        setDraft((current) => current === acceptedDraft ? "" : current);
        await loadQueue();
        if (generationRef.current !== generation) return;
        stagedChannelRef.current?.notify();
        setError(null);
        setErrorCode(null);
      } catch (failure) {
        if (generationRef.current !== generation) return;
        setError(stageErrorCopy(failure));
      } finally {
        if (generationRef.current === generation) {
          stageWritingRef.current = false;
          setStageWriting(false);
          focusComposer();
        }
      }
      return;
    }
    if (action.kind === "answer") {
      await startAnswer(semanticAnswer);
      return;
    }
    if (action.kind === "continue") {
      await startContinue();
      return;
    }
    await stopTurn();
  // startPrompt/startAnswer/startContinue are declarations backed by current refs.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [action, draft, focusComposer, loadQueue, options.researcherId, options.threadId, refresh, semanticAnswer, stopTurn]);

  const removeStaged = useCallback(async (item: StagedInput) => {
    if (queueLocked) return;
    storeRef.current ??= new StagedInputStore();
    try {
      await storeRef.current.delete(item);
      await loadQueue();
      stagedChannelRef.current?.notify();
    } catch (failure) {
      setError(stageErrorCopy(failure));
    }
  }, [loadQueue, queueLocked]);

  const editStaged = useCallback(async (item: StagedInput) => {
    if (queueLocked || question !== null || draft.length !== 0 || item.status !== "staged") return;
    setDraft(item.content);
    focusComposer();
    try {
      storeRef.current ??= new StagedInputStore();
      await storeRef.current.delete(item);
      await loadQueue();
      stagedChannelRef.current?.notify();
    } catch (failure) {
      setError(stageErrorCopy(failure));
    }
  }, [draft.length, focusComposer, loadQueue, question, queueLocked, setDraft]);

  const steerStaged = useCallback(async (item: StagedInput) => {
    const turnId = sessionRef.current?.current_turn?.id;
    if (
      queueLocked
      || turnId === undefined
      || sessionRef.current?.current_turn?.status !== "running"
      || queueRef.current[0]?.inputId !== item.inputId
      || item.status !== "staged"
    ) return;
    storeRef.current ??= new StagedInputStore();
    let submitting: StagedInput | null = null;
    try {
      submitting = await storeRef.current.markSubmitting(item, tabIdRef.current);
      await loadQueue();
      stagedChannelRef.current?.notify();
      const receipt = await steerChat(options.threadId, {
        content: item.content,
        expectedTurnId: turnId,
        inputId: item.inputId,
      });
      if (receipt.status === "accepted") {
        await storeRef.current.removeAccepted(submitting);
        await loadQueue();
        stagedChannelRef.current?.notify();
        await refresh();
      } else if (receipt.status === "pending") {
        setRecovery({ clearAnswer: false, commandId: item.inputId, draft: null, item: submitting });
        setLocalCommand("recovering");
      } else {
        await storeRef.current.release(submitting);
        await loadQueue();
        stagedChannelRef.current?.notify();
        setError(commandErrorCopy(receipt.error_code));
      }
    } catch (failure) {
      if (failure instanceof ChatCommandAcceptanceUnknownError) {
        setRecovery({ clearAnswer: false, commandId: item.inputId, draft: null, item: submitting ?? item });
        setLocalCommand("recovering");
      } else {
        await storeRef.current.release(submitting ?? item).catch(() => undefined);
        await loadQueue();
        stagedChannelRef.current?.notify();
        setError(apiErrorCopy(failure));
      }
    }
    focusComposer();
  }, [focusComposer, loadQueue, options.threadId, queueLocked, refresh]);

  const loadOlder = useCallback(async (): Promise<boolean> => {
    if (nextCursor === null || loadingOlder) return false;
    setLoadingOlder(true);
    try {
      const page = await loadTimelinePage(options.threadId, nextCursor);
      setTurns((current) => prependOlderTurns(current, page.turns));
      setNextCursor(page.next_cursor);
      setOlderTimelineError(false);
      return true;
    } catch {
      setOlderTimelineError(true);
      return false;
    } finally {
      setLoadingOlder(false);
    }
  }, [loadingOlder, nextCursor, options.threadId]);

  const retryTimeline = useCallback(async () => {
    if (olderTimelineError) {
      await loadOlder();
      return;
    }
    await refresh();
  }, [loadOlder, olderTimelineError, refresh]);

  const retryRecovery = useCallback(async () => {
    if (recovery === null) {
      setError(null);
      setErrorCode(null);
      await refresh();
      await loadQueue();
      return;
    }
    await reconcileCommand(recovery, generationRef.current, true);
  // reconcileCommand is intentionally scoped to the current controller generation.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadQueue, recovery, refresh]);

  useEffect(() => {
    generationRef.current += 1;
    sessionEstablishedRef.current = options.existingSession;
    observedActiveTurnsRef.current.clear();
    handledCompletionsRef.current.clear();
    completionDeliveriesRef.current.clear();
    watchedTitlesRef.current.clear();
    setSession(options.existingSession ? initialSessionRef.current ?? null : null);
    setOpening(options.existingSession && initialSessionRef.current === undefined);
    setLocalCommand("none");
    setRecovery(null);
    setErrorCode(null);
    setMessageDraft("");
    setAnswerDraft(null);
    setSubmittingQuestion(null);
    stopInFlightRef.current = false;
    setTurns([]);
    timelineInitializedRef.current = false;
    setNextCursor(null);
    setLatestTimelineError(false);
    setOlderTimelineError(false);
    setQueueLocked(false);
    stageWritingRef.current = false;
    setStageWriting(false);
    const controller = new AbortController();
    const generation = generationRef.current;
    void loadQueue();
    if (options.existingSession) {
      void Promise.all([
        loadAgentSession(options.threadId, controller.signal),
        loadLatestTimeline(controller.signal),
      ]).then(([next]) => {
        if (generationRef.current !== generation) return;
        observeSession(next, generation);
        setOpening(false);
      }).catch((failure: unknown) => {
        if (generationRef.current !== generation) return;
        if (!(failure instanceof DOMException && failure.name === "AbortError")) {
          setError("The Chat could not be opened.");
          setOpening(false);
        }
      });
    }
    const channel = createStagedInputChannel(
      options.researcherId,
      options.threadId,
      () => { void loadQueue(); },
    );
    stagedChannelRef.current = channel;
    return () => {
      generationRef.current += 1;
      controller.abort();
      channel.close();
      if (stagedChannelRef.current === channel) stagedChannelRef.current = null;
    };
  }, [loadLatestTimeline, loadQueue, observeSession, options.researcherId, options.threadId]);

  useEffect(() => {
    if (session?.id === undefined) return;
    const controller = new AbortController();
    let requestInFlight = false;
    const poll = () => {
      if (requestInFlight || controller.signal.aborted) return;
      requestInFlight = true;
      const generation = generationRef.current;
      const previous = sessionRef.current;
      void loadAgentSession(options.threadId, controller.signal)
        .then(async (next) => {
          if (generationRef.current !== generation) return;
          const status = next.current_turn?.status;
          const timelineChanged = (
            status === "running"
            || status === "stopping"
            || status === "waiting_for_user"
            || previous?.version !== next.version
            || previous?.current_turn?.id !== next.current_turn?.id
            || previous?.current_turn?.status !== next.current_turn?.status
            || previous?.latest_turn?.id !== next.latest_turn?.id
            || previous?.latest_turn?.status !== next.latest_turn?.status
          );
          const projectionMustLead = previous?.current_turn !== null
            && previous?.current_turn !== undefined
            && (
              next.current_turn?.id !== previous.current_turn.id
              || (
                next.current_turn?.status === "waiting_for_user"
                && previous.current_turn.status !== "waiting_for_user"
              )
            );
          if (timelineChanged && projectionMustLead) {
            await loadLatestTimeline(controller.signal);
            if (generationRef.current !== generation) return;
          }
          observeSession(next, generation);
          if (timelineChanged && !projectionMustLead) {
            await loadLatestTimeline(controller.signal);
          }
        })
        .catch(() => undefined)
        .finally(() => { requestInFlight = false; });
    };
    const interval = window.setInterval(poll, 750);
    return () => {
      controller.abort();
      window.clearInterval(interval);
    };
  }, [loadLatestTimeline, observeSession, options.threadId, session?.id]);

  const latestTurnStatus = session?.latest_turn?.status ?? null;
  const latestTurnId = session?.latest_turn?.id ?? null;
  const statusAnnouncement = error ?? statusCopy(phase, latestTurnStatus, queue.length);
  return {
    action,
    answerSelections,
    currentTurnId,
    draft,
    draftBytes,
    editStaged,
    error,
    errorCode,
    executeMainAction,
    focusComposer,
    hasFirstAssistantText,
    loadOlder,
    loadingOlder,
    latestTurnId,
    latestTurnStatus,
    nextCursor,
    phase,
    question,
    queue,
    queueLocked,
    refresh,
    removeStaged,
    retryRecovery,
    retryTimeline,
    setAnswerSelections,
    setDraft,
    steerStaged,
    stopTurn,
    statusAnnouncement,
    textareaRef,
    timelineError: latestTimelineError || olderTimelineError,
    turns,
  };
}

export function mergeLatestTurns(
  current: readonly TimelineTurn[],
  latest: readonly TimelineTurn[],
): readonly TimelineTurn[] {
  const latestIds = new Set(latest.map((turn) => turn.id));
  const older = current.filter((turn) => !latestIds.has(turn.id));
  return [...older, ...latest];
}

export function prependOlderTurns(
  current: readonly TimelineTurn[],
  older: readonly TimelineTurn[],
): readonly TimelineTurn[] {
  const existing = new Set(current.map((turn) => turn.id));
  return [...older.filter((turn) => !existing.has(turn.id)), ...current];
}

function stageErrorCopy(error: unknown): string {
  if (error instanceof StagedInputStoreError && error.code === "STAGE_LIMIT") {
    return "This Chat already has 20 staged inputs. Send, edit, or delete one before staging another.";
  }
  if (error instanceof StagedInputStoreError && error.code === "STAGE_STORAGE_CORRUPT") {
    return "Staged input storage is damaged. Nothing was deleted and queue actions are disabled.";
  }
  return "The input could not be staged. Your draft is still available.";
}

function apiErrorCopy(error: unknown): string {
  if (error instanceof ChatApiError) return commandErrorCopy(error.code);
  return "The Agent service is unavailable. No input was discarded.";
}

function commandErrorCopy(code: string | null): string {
  switch (code) {
    case "STALE_CHAT_TURN": return "The active Turn changed before this command arrived. Refresh and try again.";
    case "CHAT_TURN_NOT_STEERABLE": return "This Turn cannot accept Steer input.";
    case "CHAT_QUESTION_NOT_FOUND": return "The question is no longer waiting for an answer.";
    case "CHAT_COMMAND_CONFLICT": return "This input identity was already used for a different command.";
    case "CHAT_CAPABILITY_UNAVAILABLE": return "The requested runtime capability is no longer available.";
    case "CHAT_STORAGE_FAILURE": return "Chat storage is temporarily unavailable. Your local input was retained.";
    default: return "The Agent command could not be completed. Your local input was retained.";
  }
}

function rejectedRunErrorCopy(code: string): string {
  if (code === "AGENT_CAPACITY") {
    return "Agent at capacity. The Turn was not accepted and your input was restored.";
  }
  if (code === "AUTHENTICATION_REQUIRED") {
    return "Authentication was rejected before the Turn was accepted. Your input was restored.";
  }
  return "The command was rejected before the Turn was accepted. Your input was restored.";
}

function statusCopy(phase: ChatPhase, latestTurnStatus: ChatTurnStatus | null, queued: number): string {
  const queueCopy = queued === 0 ? "" : ` ${queued} input${queued === 1 ? "" : "s"} staged.`;
  switch (phase) {
    case "new": return `Ready for a new Chat.${queueCopy}`;
    case "opening": return `Opening the Turn.${queueCopy}`;
    case "idle": {
      const outcome = latestTurnStatus === "completed"
        ? "Run complete."
        : latestTurnStatus === "failed"
          ? "Run failed."
          : latestTurnStatus === "stopped" ? "Turn stopped." : "Ready.";
      return `${outcome}${queueCopy}`;
    }
    case "active": return `Research Agent is working.${queueCopy}`;
    case "waiting_for_user": return `The Research Agent is waiting for your answer.${queueCopy}`;
    case "stopping": return `Stopping the current Turn.${queueCopy}`;
    case "recovering": return `Confirming whether the last command was accepted.${queueCopy}`;
  }
}
