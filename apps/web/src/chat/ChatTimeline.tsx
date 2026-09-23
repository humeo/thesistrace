import type { ActivityMessage } from "@ag-ui/core";
import {
  ArrowDown,
  CaretDown,
  Check,
  CheckCircle,
  CircleNotch,
  Copy,
  ListChecks,
  Question,
  StopCircle,
  WarningCircle,
  Wrench,
} from "@phosphor-icons/react";
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkCjkFriendly from "remark-cjk-friendly/parseOnly";
import { useTranslation } from "react-i18next";
import { i18n } from "../i18n";
import { formatNumber, formatTimestamp } from "../i18n/format";

import { parseResearchRunHref } from "./toolResult";
import { ResearchA2UIActivity } from "./researchA2UI";
import { progressHistory } from "./progressHistory";
import type { ChatQuestion, TimelineEntry, TimelineTurn } from "./chatProtocol";
import type { ChatConversationController } from "./useChatConversation";

const BOTTOM_THRESHOLD_PX = 24;
const NEW_TURN_TOP_GAP_PX = 96;
const SCROLL_TRANSITION_MS = 240;
const RESEARCH_MARKDOWN_REMARK_PLUGINS = [remarkGfm, remarkCjkFriendly];

type ScrollAnchor = Readonly<{ top: number; turnId: string }>;
type ToolEntry = Extract<TimelineEntry, { kind: "tool_activity" }> & { questionDetails?: { question: string; answer?: string } };
type TurnSegment = TimelineEntry | Readonly<{ entries: readonly ToolEntry[]; kind: "tool_group" }>;
export type ChatAnnouncement = "copied" | "copyFailed";

export function ChatTimeline({
  controller,
  onAnnounce,
}: {
  controller: ChatConversationController;
  onAnnounce: (message: ChatAnnouncement) => void;
}) {
  const { t } = useTranslation("chat");
  const scrollRef = useRef<HTMLDivElement>(null);
  const topSentinelRef = useRef<HTMLDivElement>(null);
  const previousScrollTopRef = useRef(0);
  const touchYRef = useRef<number | null>(null);
  const anchorRef = useRef<ScrollAnchor | null>(null);
  const initialPositionedRef = useRef(false);
  const olderRequestRef = useRef(false);
  const latestTurnRef = useRef(controller.turns.at(-1)?.id);
  const pendingTransitionRef = useRef(false);
  const scrollFrameRef = useRef<number | null>(null);
  const [positionedTurnId, setPositionedTurnId] = useState<string | null>(null);
  const [turnMinHeight, setTurnMinHeight] = useState(0);
  const [following, setFollowing] = useState(true);
  const [latestBelowViewport, setLatestBelowViewport] = useState(false);
  const empty = controller.turns.length === 0;
  const latestTurnId = controller.turns.at(-1)?.id;

  useLayoutEffect(() => {
    const viewport = scrollRef.current;
    const content = viewport?.querySelector<HTMLElement>(".chat-timeline-content");
    if (!viewport || !content) return;
    const measure = () => setTurnMinHeight(Math.max(0,
      viewport.clientHeight - NEW_TURN_TOP_GAP_PX - parseFloat(getComputedStyle(content).paddingBottom),
    ));
    measure();
    const observer = new ResizeObserver(() => {
      measure();
      if (following && initialPositionedRef.current && anchorRef.current === null
        && scrollFrameRef.current === null) {
        viewport.scrollTop = viewport.scrollHeight;
        previousScrollTopRef.current = viewport.scrollTop;
      }
      updateLatestVisibility();
    });
    observer.observe(viewport);
    observer.observe(content);
    const latestResponse = content.querySelector(".chat-turn:last-child .chat-turn-response");
    if (latestResponse) observer.observe(latestResponse);
    return () => observer.disconnect();
  }, [empty, latestTurnId, following]);

  useLayoutEffect(() => {
    const viewport = scrollRef.current;
    if (viewport === null) return;
    const latest = controller.turns.at(-1);
    if (latest && latest.id !== latestTurnRef.current) {
      const previous = latestTurnRef.current;
      latestTurnRef.current = latest.id;
      // Loading an existing history keeps its compact bottom position. A new
      // Turn gets enough room to place its prompt near the top, even if short.
      if (previous !== undefined || latest.completed_at === null) {
        cancelScrollTransition();
        pendingTransitionRef.current = true;
        setPositionedTurnId(latest.id);
        setFollowing(true);
        return;
      }
    }
    const anchor = anchorRef.current;
    if (anchor !== null) {
      const target = [...viewport.querySelectorAll<HTMLElement>("[data-turn-id]")]
        .find((element) => element.dataset.turnId === anchor.turnId);
      if (target !== undefined) viewport.scrollTop += target.getBoundingClientRect().top - anchor.top;
      anchorRef.current = null;
      previousScrollTopRef.current = viewport.scrollTop;
      return;
    }
    if (pendingTransitionRef.current) {
      pendingTransitionRef.current = false;
      scrollToLatest();
      initialPositionedRef.current = true;
      return;
    }
    // Stream updates must not replace an in-flight transition with a jump.
    if (scrollFrameRef.current !== null) return;
    if (!initialPositionedRef.current || following) {
      viewport.scrollTop = viewport.scrollHeight;
      previousScrollTopRef.current = viewport.scrollTop;
      initialPositionedRef.current = true;
    }
    updateLatestVisibility();
  }, [controller.turns, following, positionedTurnId, turnMinHeight]);

  useEffect(() => () => cancelScrollTransition(), []);

  function cancelScrollTransition(): void {
    if (scrollFrameRef.current !== null) cancelAnimationFrame(scrollFrameRef.current);
    scrollFrameRef.current = null;
  }

  function scrollToLatest(): void {
    const viewport = scrollRef.current;
    if (viewport === null) return;
    cancelScrollTransition();
    const start = viewport.scrollTop;
    const startedAt = performance.now();
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      viewport.scrollTop = viewport.scrollHeight;
      previousScrollTopRef.current = viewport.scrollTop;
      return;
    }
    const step = (now: number) => {
      const progress = Math.min(1, (now - startedAt) / SCROLL_TRANSITION_MS);
      const target = Math.max(0, viewport.scrollHeight - viewport.clientHeight);
      viewport.scrollTop = start + (target - start) * (1 - (1 - progress) ** 3);
      previousScrollTopRef.current = viewport.scrollTop;
      scrollFrameRef.current = progress < 1 ? requestAnimationFrame(step) : null;
    };
    scrollFrameRef.current = requestAnimationFrame(step);
  }

  function stopFollowing(): void {
    cancelScrollTransition();
    setFollowing(false);
  }

  function updateLatestVisibility(): void {
    const viewport = scrollRef.current;
    const response = viewport?.querySelector(".chat-turn:last-child .chat-turn-response");
    // The Turn's minimum height includes empty space for positioning a new
    // prompt. Only the actual response can contain unread content below us.
    setLatestBelowViewport(Boolean(viewport && response
      && response.getBoundingClientRect().bottom > viewport.getBoundingClientRect().bottom + BOTTOM_THRESHOLD_PX));
  }

  async function loadOlder(): Promise<void> {
    const viewport = scrollRef.current;
    if (viewport === null || olderRequestRef.current || controller.nextCursor === null) return;
    olderRequestRef.current = true;
    const viewportBounds = viewport.getBoundingClientRect();
    const first = [...viewport.querySelectorAll<HTMLElement>("[data-turn-id]")]
      .find((element) => {
        const bounds = element.getBoundingClientRect();
        return bounds.bottom > viewportBounds.top && bounds.top < viewportBounds.bottom;
      });
    if (first !== undefined && first.dataset.turnId !== undefined) {
      anchorRef.current = { top: first.getBoundingClientRect().top, turnId: first.dataset.turnId };
    }
    try {
      const loaded = await controller.loadOlder();
      if (!loaded) anchorRef.current = null;
    } finally {
      olderRequestRef.current = false;
    }
  }

  useEffect(() => {
    const sentinel = topSentinelRef.current;
    if (
      sentinel === null
      || controller.nextCursor === null
      || controller.timelineError
      || typeof IntersectionObserver === "undefined"
    ) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) void loadOlder();
    }, { root: scrollRef.current, rootMargin: "160px 0px 0px" });
    observer.observe(sentinel);
    return () => observer.disconnect();
  // loadOlder reads the current controller and is deliberately recreated for each page state.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [controller.loadingOlder, controller.nextCursor, controller.timelineError]);

  function updateFollowing(): void {
    const viewport = scrollRef.current;
    if (viewport === null) return;
    updateLatestVisibility();
    if (scrollFrameRef.current !== null) return;
    const atBottom = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight <= BOTTOM_THRESHOLD_PX;
    if (viewport.scrollTop < previousScrollTopRef.current && !atBottom) setFollowing(false);
    else if (atBottom) setFollowing(true);
    previousScrollTopRef.current = viewport.scrollTop;
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    if (["ArrowUp", "PageUp", "Home"].includes(event.key)) stopFollowing();
  }

  function backToLatest(): void {
    const viewport = scrollRef.current;
    if (viewport === null) return;
    scrollToLatest();
    setFollowing(true);
  }

  return (
    <div className="chat-timeline-shell">
      <div
        aria-label={t("timeline")}
        aria-live="off"
        className={`chat-timeline${empty ? " chat-timeline-empty" : ""}`}
        onKeyDown={handleKeyDown}
        onScroll={updateFollowing}
        onTouchMove={(event) => {
          const y = event.touches[0]?.clientY;
          if (y !== undefined && touchYRef.current !== null && y > touchYRef.current) stopFollowing();
          touchYRef.current = y ?? null;
        }}
        onTouchStart={(event) => {
          if (scrollFrameRef.current !== null) stopFollowing();
          touchYRef.current = event.touches[0]?.clientY ?? null;
        }}
        onWheel={(event) => { if (event.deltaY < 0 || scrollFrameRef.current !== null) stopFollowing(); }}
        ref={scrollRef}
        role="log"
        tabIndex={0}
      >
        {empty ? <ChatIntroduction opening={controller.phase === "opening"} /> : (
          <div className="chat-timeline-content">
            <div aria-hidden="true" className="chat-top-sentinel" ref={topSentinelRef} />
            {controller.loadingOlder ? (
              <CircleNotch aria-label={t("loadingEarlier")} className="chat-timeline-loading chat-spinning" size={15} />
            ) : null}
            {controller.timelineError ? (
              <div className="chat-timeline-error">
                <span>{t("timelineError")}</span>
                <button
                  className="button-quiet"
                  onClick={() => void controller.retryTimeline()}
                  type="button"
                >
                  {t("retry")}
                </button>
              </div>
            ) : null}
            {controller.turns.map((turn) => (
              <TimelineTurnView
                controller={controller}
                key={turn.id}
                minHeight={turn.id === positionedTurnId ? turnMinHeight : undefined}
                onAnnounce={onAnnounce}
                turn={turn}
              />
            ))}
          </div>
        )}
      </div>
      {!following && latestBelowViewport && !empty ? (
        <button className="chat-back-to-latest" onClick={backToLatest} type="button">
          <ArrowDown aria-hidden="true" size={14} />
          {t("backToLatest")}
        </button>
      ) : null}
    </div>
  );
}

function TimelineTurnView({
  controller,
  minHeight,
  onAnnounce,
  turn,
}: {
  controller: ChatConversationController;
  minHeight?: number;
  onAnnounce: (message: ChatAnnouncement) => void;
  turn: TimelineTurn;
}) {
  const { t } = useTranslation("chat");
  const hiddenProgress = progressHistory(turn);
  const visibleEntries = questionToolEntries(turn.entries).filter((entry) => !hiddenProgress.has(entry.entry_id));
  const firstAssistantIndex = visibleEntries.findIndex((entry) => entry.kind !== "user_input");
  const leadingCount = firstAssistantIndex < 0 ? visibleEntries.length : firstAssistantIndex;
  const leading = visibleEntries.slice(0, leadingCount);
  const assistantEntries = visibleEntries.slice(leadingCount);
  const ended = ["completed", "failed", "stopped"].includes(turn.status);
  const [workOpen, setWorkOpen] = useState(!ended);
  useEffect(() => { setWorkOpen(!ended); }, [ended]);
  const lastTool = assistantEntries.reduce((last, entry, index) => entry.kind === "tool_activity" ? index : last, -1);
  const processEntries = assistantEntries.filter((entry, index) => (
    entry.kind === "tool_activity"
    || (entry.kind === "assistant_message" && !entry.payload.recovery && (index < lastTool || (!ended && lastTool >= 0)))
  ));
  const processIds = new Set(processEntries.map((entry) => entry.entry_id));
  const resultEntries = assistantEntries.filter((entry) => !processIds.has(entry.entry_id));
  const assistantText = turn.entries
    .filter((entry): entry is Extract<TimelineEntry, { kind: "assistant_message" }> => (
      entry.kind === "assistant_message" && entry.payload.content.length > 0
    ))
    .map((entry) => entry.payload.content)
    .join("\n\n");
  const activeWithoutText = turn.id === controller.currentTurnId
    && controller.phase === "active"
    && !controller.hasFirstAssistantText;
  const runningTools = turn.entries.filter((entry): entry is ToolEntry =>
    entry.kind === "tool_activity" && entry.payload.status === "running");
  const showCurrentActivity = !ended && turn.id === controller.currentTurnId
    && (controller.phase === "active" || turn.status === "stopping")
    && (!activeWithoutText || runningTools.length > 0);
  const latestTool = runningTools.at(-1);
  const currentActivity = turn.status === "stopping" ? t("stoppingActivity")
    : latestTool ? `${t("runningTool", { name: latestTool.payload.name.replaceAll("_", " ") })}${runningTools.length > 1 ? t("runningTools", { count: runningTools.length }) : ""}`
    : turn.entries.some(entry => entry.kind === "assistant_message" && entry.payload.status === "streaming")
      ? t("writingResponse") : t("preparingActivity");
  const showAssistantSection = assistantEntries.length > 0 || activeWithoutText;

  const renderEntries = (entries: readonly TimelineEntry[]) => segmentTurnEntries(entries).map((segment) => (
        segment.kind === "tool_group"
          ? <ToolActivityGroup entries={segment.entries} key={`tools:${segment.entries[0]?.entry_id}`} />
          : <TimelineItem controller={controller} entry={segment} key={segment.entry_id} onAnnounce={onAnnounce} />
      ));

  return (
    <section className="chat-turn" data-turn-id={turn.id} style={{ minHeight }}>
      {leading.map((entry) => (
        <TimelineItem controller={controller} entry={entry} key={entry.entry_id} onAnnounce={onAnnounce} />
      ))}
      <div className="chat-turn-response">
        {!showAssistantSection ? null : (
          <div className="chat-turn-assistant-meta chat-work-meta">
            {processEntries.length > 0 ? (
              <details className="chat-work-history" open={workOpen} onToggle={(event) => setWorkOpen(event.currentTarget.open)}>
                <summary><WorkedFor turn={turn} /><CaretDown aria-hidden="true" size={14} /></summary>
                <div className="chat-work-content">{renderEntries(processEntries)}</div>
              </details>
            ) : <span><WorkedFor turn={turn} /></span>}
          </div>
        )}
        {renderEntries(resultEntries)}
        {showCurrentActivity ? (
          <div className={`chat-current-activity${turn.status === "stopping" ? "" : " chat-current-activity-running"}`} role="status" aria-live="polite">
            <span>{currentActivity}</span>
          </div>
        ) : null}
        {activeWithoutText && !showCurrentActivity ? (
          <div aria-label={t("preparingResponse")} className="chat-response-indicator">
            <span aria-hidden="true" />
          </div>
        ) : null}
        {assistantText.length > 0 || turn.completed_at !== null ? (
          <footer className="chat-response-footer">
            {assistantText.length > 0 ? <CopyTextButton content={assistantText} label={t("copyResponse")} onAnnounce={onAnnounce} /> : null}
            {turn.completed_at !== null ? <time dateTime={turn.completed_at} title={formatTimestamp(turn.completed_at, { dateStyle: "medium", timeStyle: "medium" })}>
              {formatTimestamp(turn.completed_at, { hour: "numeric", minute: "2-digit" })}
            </time> : null}
          </footer>
        ) : null}
      </div>
    </section>
  );
}

function WorkedFor({ turn }: { turn: TimelineTurn }) {
  const { t } = useTranslation("chat");
  const ticking = turn.completed_at === null && (turn.status === "running" || turn.status === "stopping");
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!ticking) return;
    const interval = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(interval);
  }, [ticking]);
  const startedAt = Date.parse(turn.started_at);
  const completedAt = turn.completed_at === null ? now : Date.parse(turn.completed_at);
  return t(ticking ? "workingFor" : "workedFor", { duration: formatDuration(Math.max(0, completedAt - startedAt)) });
}

function TimelineItem({
  controller,
  entry,
  onAnnounce,
}: {
  controller: ChatConversationController;
  entry: TimelineEntry;
  onAnnounce: (message: ChatAnnouncement) => void;
}) {
  const { t } = useTranslation("chat");
  if (entry.kind === "user_input") {
    return (
      <article className="chat-message chat-message-user" data-entry-id={entry.entry_id}>
        <div className="chat-message-actions">
          <CopyTextButton content={entry.payload.content} label={t("copyMessage")} onAnnounce={onAnnounce} />
        </div>
        <div className="chat-message-content">{entry.payload.content}</div>
        {entry.payload.source === "steer" ? <span className="chat-input-source">{t("steered")}</span> : null}
      </article>
    );
  }
  if (entry.kind === "assistant_message") {
    return (
      <article className="chat-message chat-message-assistant" data-entry-id={entry.entry_id}>
        <div className="chat-message-content">
          <AssistantMarkdown content={entry.payload.content} streaming={entry.payload.status === "streaming"} />
        </div>
        {entry.payload.recovery ? (
          <span className="chat-assistant-outcome" role="status">
            {t(entry.payload.recovery.status === "recovering" ? "partialRecovering"
              : entry.payload.recovery.status === "succeeded" ? "partialReplaced"
              : entry.payload.recovery.attempts === 1 ? "partialRecoveryFailed"
              : entry.payload.recovery.cause === "OUTPUT_LIMIT" ? "partialOutputLimit"
              : "contextTooLarge")}
          </span>
        ) : entry.payload.status === "stopped" || entry.payload.status === "failed" ? (
          <span className={`chat-assistant-outcome chat-assistant-outcome-${entry.payload.status}`}>
            {t(entry.payload.status === "stopped" ? "partialStopped" : "partialFailed")}
          </span>
        ) : null}
      </article>
    );
  }
  if (entry.kind === "tool_activity") return <ToolActivityGroup entries={[entry]} />;
  if (entry.kind === "a2ui") {
    const message: ActivityMessage = {
      activityType: entry.payload.activityType,
      content: entry.payload.content,
      id: entry.entry_id.startsWith("a2ui:") ? entry.entry_id.slice(5) : entry.entry_id,
      role: "activity",
    };
    return <div data-entry-id={entry.entry_id}><ResearchA2UIActivity message={message} /></div>;
  }
  if (entry.kind === "question") {
    const active = controller.question?.interrupt_id === entry.payload.interrupt_id
      && entry.payload.status === "pending";
    return (
      <QuestionSurface
        active={active}
        controller={controller}
        entryId={entry.entry_id}
        question={entry.payload}
      />
    );
  }
  return <TurnOutcome entry={entry} />;
}

function ToolActivityGroup({ entries }: { entries: readonly ToolEntry[] }) {
  const { t } = useTranslation("chat");
  const counts = entries.reduce((current, entry) => ({
    active: current.active + (entry.payload.status === "running" ? 1 : 0),
    failed: current.failed + (entry.payload.status === "failed" ? 1 : 0),
    stopped: current.stopped + (entry.payload.status === "stopped" ? 1 : 0),
  }), { active: 0, failed: 0, stopped: 0 });
  const details = [
    counts.active === 0 ? null : t("toolActive", { count: counts.active }),
    counts.failed === 0 ? null : t("toolFailed", { count: counts.failed }),
    counts.stopped === 0 ? null : t("toolStopped", { count: counts.stopped }),
  ].filter((value) => value !== null);
  return (
    <details className="chat-tool-group" data-entry-id={entries[0]?.entry_id}>
      <summary>
        <Wrench aria-hidden="true" size={15} />
        <span>{t(counts.active > 0 ? "usingTools" : "usedTools", { count: entries.length })}</span>
        {details.length === 0 ? null : <small>{details.join(" · ")}</small>}
        <CaretDown aria-hidden="true" className="chat-tool-group-caret" size={13} />
      </summary>
      <ol>
        {entries.map((entry) => <ToolActivityItem entry={entry} key={entry.entry_id} />)}
      </ol>
    </details>
  );
}

function ToolActivityItem({ entry }: { entry: ToolEntry }) {
  const { t } = useTranslation("chat");
  const status = entry.payload.status;
  const Icon = status === "running"
    ? CircleNotch
    : status === "complete" ? CheckCircle : status === "stopped" ? StopCircle : WarningCircle;
  const label = t(`toolStatus.${status}`);
  return (
    <li
      aria-label={t("toolAria", { name: entry.payload.name, status: label })}
      data-entry-id={entry.entry_id}
      data-tool-name={entry.payload.name}
      data-tool-status={status}
      role="article"
    >
      <Icon aria-hidden="true" className={status === "running" ? "chat-spinning" : undefined} size={14} />
      <code>{entry.payload.name}</code>
      <span>{label}</span>
      {entry.questionDetails ? <details className="chat-tool-question"><summary>{t("questionAndAnswer")}</summary><p>{entry.questionDetails.question}</p>{entry.questionDetails.answer ? <p>{entry.questionDetails.answer}</p> : null}</details> : null}
    </li>
  );
}

function segmentTurnEntries(entries: readonly TimelineEntry[]): readonly TurnSegment[] {
  const segments: TurnSegment[] = [];
  for (const entry of entries) {
    if (entry.kind !== "tool_activity") {
      segments.push(entry);
      continue;
    }
    const previous = segments.at(-1);
    if (previous?.kind === "tool_group") {
      segments[segments.length - 1] = { entries: [...previous.entries, entry], kind: "tool_group" };
    } else {
      segments.push({ entries: [entry], kind: "tool_group" });
    }
  }
  return segments;
}

function QuestionSurface({
  active,
  controller,
  entryId,
  question,
}: {
  active: boolean;
  controller: ChatConversationController;
  entryId: string;
  question: ChatQuestion & Readonly<{ status: "pending" | "answered" | "stopped" }>;
}) {
  const { t } = useTranslation("chat");
  return (
    <section className="chat-question-activity" data-entry-id={entryId}>
      <details>
        <summary>
          <Question aria-hidden="true" size={16} />
          <span>{t(question.status === "answered" ? "questionAnswered" : question.status === "stopped" ? "questionStopped" : "askingQuestions")}</span>
          <CaretDown aria-hidden="true" size={13} />
        </summary>
        <p>{question.question}</p>
      </details>
      {active ? <button className="chat-question-waiting" onClick={controller.focusComposer} type="button">
        <ListChecks aria-hidden="true" size={16} /><span>{t("waitingAnswer")}</span>
      </button> : null}
    </section>
  );
}

function TurnOutcome({ entry }: { entry: Extract<TimelineEntry, { kind: "turn_outcome" }> }) {
  const { t } = useTranslation("chat");
  if (entry.payload.status === "completed") {
    return <div hidden aria-hidden="true" data-entry-id={entry.entry_id} data-turn-outcome="completed" />;
  }
  const explanationCode = entry.payload.errorCode === "OUTPUT_LIMIT" || entry.payload.errorCode === "CONTEXT_TOO_LARGE" || entry.payload.errorCode === "CONTEXT_COMPACTION_FAILED"
    ? entry.payload.errorCode : null;
  return (
    <div
      className={`chat-turn-outcome chat-turn-outcome-${entry.payload.status}`}
      data-entry-id={entry.entry_id}
      data-failure-code={entry.payload.errorCode}
      data-turn-outcome={entry.payload.status}
      role={entry.payload.status === "failed" ? "alert" : "status"}
    >
      {entry.payload.status === "stopped" ? <StopCircle aria-hidden="true" size={14} /> : <WarningCircle aria-hidden="true" size={14} />}
      {explanationCode === null ? <>
        <span>{t(entry.payload.status === "stopped" ? "turnStopped" : "turnFailed")}</span>
        {entry.payload.errorCode === undefined ? null : <code>{entry.payload.errorCode}</code>}
      </> : <span className="chat-turn-failure-explanation">
        <strong>{t(`agentFailures.${explanationCode}.label`)}</strong>
        <span>{t(`agentFailures.${explanationCode}.message`)}</span>
      </span>}
    </div>
  );
}

function CopyTextButton({
  content,
  label,
  onAnnounce,
}: {
  content: string;
  label: string;
  onAnnounce: (message: ChatAnnouncement) => void;
}) {
  const { t } = useTranslation("chat");
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1_500);
    return () => window.clearTimeout(timer);
  }, [copied]);
  async function copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      onAnnounce("copied");
    } catch {
      onAnnounce("copyFailed");
    }
  }
  return (
    <button aria-label={label} disabled={content.length === 0} onClick={() => void copy()} type="button">
      {copied ? <Check aria-hidden="true" size={14} /> : <Copy aria-hidden="true" size={14} />}
      <span>{t("copy")}</span>
    </button>
  );
}

function formatDuration(milliseconds: number): string {
  const seconds = Math.floor(milliseconds / 1_000);
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return minutes === 0
    ? i18n.t("chat:durationSeconds", { seconds: formatNumber(remainingSeconds) })
    : i18n.t("chat:durationMinutes", { minutes: formatNumber(minutes), seconds: formatNumber(remainingSeconds) });
}

export function AssistantMarkdown({ content, streaming = false }: { content: string; streaming?: boolean }) {
  return (
    <div className={`chat-assistant-markdown chat-assistant-markdown-${streaming ? "streaming" : "static"}`}>
      <ReactMarkdown
        components={{ a: SafeMarkdownLink, code: SafeMarkdownCode, img: HiddenMarkdownImage, pre: SafeMarkdownPre }}
        remarkPlugins={RESEARCH_MARKDOWN_REMARK_PLUGINS}
        skipHtml
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function SafeMarkdownLink({ children, href }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { node?: unknown }) {
  const safeHref = parseResearchRunHref(href);
  return safeHref === null
    ? <span className="chat-markdown-link-disabled">{children}</span>
    : <a className="chat-markdown-run-link" href={safeHref}>{children}</a>;
}

function SafeMarkdownCode({ children, className }: React.HTMLAttributes<HTMLElement> & { node?: unknown }) {
  return <code className={className}>{children}</code>;
}

function SafeMarkdownPre({ children }: React.HTMLAttributes<HTMLPreElement> & { node?: unknown }) {
  return <pre>{children}</pre>;
}

function HiddenMarkdownImage(_props: React.ImgHTMLAttributes<HTMLImageElement> & { node?: unknown }) {
  return null;
}

export function ChatIntroduction({ opening = false }: { opening?: boolean }) {
  const { t } = useTranslation("chat");
  return (
    <section className="chat-empty-state">
      <span className="chat-empty-symbol" aria-hidden="true">α</span>
      <p className="eyebrow">{t("researchAgent")}</p>
      <h1>{t("introTitle")}</h1>
      <p className="chat-empty-copy">
        {t("introDescription")}
      </p>
      {opening ? <p className="chat-history-status">{t("openingConversation")}</p> : null}
    </section>
  );
}

function questionToolEntries(entries: readonly TimelineEntry[]): TimelineEntry[] {
  const answers = new Map<string, string>();
  let questionId: string | undefined;
  for (const entry of entries) {
    if (entry.kind === "question") questionId = entry.entry_id;
    if (entry.kind === "user_input" && entry.payload.source === "answer" && questionId !== undefined) {
      answers.set(questionId, entry.payload.content);
    }
  }
  return entries.flatMap((entry): TimelineEntry[] => {
    if (entry.kind === "user_input" && entry.payload.source === "answer") return [];
    if (entry.kind !== "question" || entry.payload.status === "pending") return [entry];
    const tool: ToolEntry = {
      ...entry, kind: "tool_activity",
      payload: { name: "ask_user", status: entry.payload.status === "answered" ? "complete" : "stopped" },
      questionDetails: { question: entry.payload.question, answer: answers.get(entry.entry_id) },
    };
    return [tool];
  });
}
