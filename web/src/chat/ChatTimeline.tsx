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

import { parseResearchRunHref } from "./toolResult";
import { ResearchA2UIActivity } from "./researchA2UI";
import type { ChatQuestion, TimelineEntry, TimelineTurn } from "./chatProtocol";
import type { ChatConversationController } from "./useChatConversation";

const BOTTOM_THRESHOLD_PX = 24;
const RESEARCH_MARKDOWN_REMARK_PLUGINS = [remarkGfm];

type ScrollAnchor = Readonly<{ top: number; turnId: string }>;
type ToolEntry = Extract<TimelineEntry, { kind: "tool_activity" }>;
type TurnSegment = TimelineEntry | Readonly<{ entries: readonly ToolEntry[]; kind: "tool_group" }>;

export function ChatTimeline({
  controller,
  onAnnounce,
}: {
  controller: ChatConversationController;
  onAnnounce: (message: string) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const topSentinelRef = useRef<HTMLDivElement>(null);
  const previousScrollTopRef = useRef(0);
  const touchYRef = useRef<number | null>(null);
  const anchorRef = useRef<ScrollAnchor | null>(null);
  const initialPositionedRef = useRef(false);
  const olderRequestRef = useRef(false);
  const [following, setFollowing] = useState(true);

  useLayoutEffect(() => {
    const viewport = scrollRef.current;
    if (viewport === null) return;
    const anchor = anchorRef.current;
    if (anchor !== null) {
      const target = [...viewport.querySelectorAll<HTMLElement>("[data-turn-id]")]
        .find((element) => element.dataset.turnId === anchor.turnId);
      if (target !== undefined) viewport.scrollTop += target.getBoundingClientRect().top - anchor.top;
      anchorRef.current = null;
      previousScrollTopRef.current = viewport.scrollTop;
      return;
    }
    if (!initialPositionedRef.current || following) {
      viewport.scrollTop = viewport.scrollHeight;
      previousScrollTopRef.current = viewport.scrollTop;
      initialPositionedRef.current = true;
    }
  }, [controller.turns, following]);

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
    const atBottom = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight <= BOTTOM_THRESHOLD_PX;
    if (viewport.scrollTop < previousScrollTopRef.current && !atBottom) setFollowing(false);
    else if (atBottom) setFollowing(true);
    previousScrollTopRef.current = viewport.scrollTop;
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    if (["ArrowUp", "PageUp", "Home"].includes(event.key)) setFollowing(false);
  }

  function backToLatest(): void {
    const viewport = scrollRef.current;
    if (viewport === null) return;
    viewport.scrollTo({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
      top: viewport.scrollHeight,
    });
    setFollowing(true);
  }

  const empty = controller.turns.length === 0;
  return (
    <div className="chat-timeline-shell">
      <div
        aria-label="Conversation timeline"
        aria-live="off"
        className={`chat-timeline${empty ? " chat-timeline-empty" : ""}`}
        onKeyDown={handleKeyDown}
        onScroll={updateFollowing}
        onTouchMove={(event) => {
          const y = event.touches[0]?.clientY;
          if (y !== undefined && touchYRef.current !== null && y > touchYRef.current) setFollowing(false);
          touchYRef.current = y ?? null;
        }}
        onTouchStart={(event) => { touchYRef.current = event.touches[0]?.clientY ?? null; }}
        onWheel={(event) => { if (event.deltaY < 0) setFollowing(false); }}
        ref={scrollRef}
        role="log"
        tabIndex={0}
      >
        {empty ? <ChatIntroduction opening={controller.phase === "opening"} /> : (
          <div className="chat-timeline-content">
            <div aria-hidden="true" className="chat-top-sentinel" ref={topSentinelRef} />
            {controller.loadingOlder ? (
              <CircleNotch aria-label="Loading earlier Turns" className="chat-timeline-loading chat-spinning" size={15} />
            ) : null}
            {controller.timelineError ? (
              <div className="chat-timeline-error">
                <span>Conversation history could not be updated.</span>
                <button
                  className="button-quiet"
                  onClick={() => void controller.retryTimeline()}
                  type="button"
                >
                  Retry
                </button>
              </div>
            ) : null}
            {controller.turns.map((turn) => (
              <TimelineTurnView
                controller={controller}
                key={turn.id}
                onAnnounce={onAnnounce}
                turn={turn}
              />
            ))}
          </div>
        )}
      </div>
      {!following && !empty ? (
        <button className="chat-back-to-latest" onClick={backToLatest} type="button">
          <ArrowDown aria-hidden="true" size={14} />
          Back to latest
        </button>
      ) : null}
    </div>
  );
}

function TimelineTurnView({
  controller,
  onAnnounce,
  turn,
}: {
  controller: ChatConversationController;
  onAnnounce: (message: string) => void;
  turn: TimelineTurn;
}) {
  const firstAssistantIndex = turn.entries.findIndex((entry) => entry.kind !== "user_input");
  const leadingCount = firstAssistantIndex < 0 ? turn.entries.length : firstAssistantIndex;
  const leading = turn.entries.slice(0, leadingCount);
  const assistantEntries = turn.entries.slice(leadingCount);
  const assistantText = turn.entries
    .filter((entry): entry is Extract<TimelineEntry, { kind: "assistant_message" }> => (
      entry.kind === "assistant_message" && entry.payload.content.length > 0
    ))
    .map((entry) => entry.payload.content)
    .join("\n\n");
  const activeWithoutText = turn.id === controller.currentTurnId
    && controller.phase === "active"
    && !controller.hasFirstAssistantText;
  const showAssistantSection = assistantEntries.length > 0 || activeWithoutText;

  return (
    <section className="chat-turn" data-turn-id={turn.id}>
      {leading.map((entry) => (
        <TimelineItem controller={controller} entry={entry} key={entry.entry_id} onAnnounce={onAnnounce} />
      ))}
      {!showAssistantSection ? null : (
        <div className="chat-turn-assistant-meta">
          <span><WorkedFor turn={turn} /></span>
          {assistantText.length === 0 ? null : (
            <CopyTextButton content={assistantText} label="Copy response" onAnnounce={onAnnounce} />
          )}
        </div>
      )}
      {segmentTurnEntries(assistantEntries).map((segment) => (
        segment.kind === "tool_group"
          ? <ToolActivityGroup entries={segment.entries} key={`tools:${segment.entries[0]?.entry_id}`} />
          : <TimelineItem controller={controller} entry={segment} key={segment.entry_id} onAnnounce={onAnnounce} />
      ))}
      {activeWithoutText ? (
        <div aria-label="Research Agent is preparing a response" className="chat-response-indicator">
          <span aria-hidden="true" />
        </div>
      ) : null}
    </section>
  );
}

function WorkedFor({ turn }: { turn: TimelineTurn }) {
  const ticking = turn.completed_at === null && (turn.status === "running" || turn.status === "stopping");
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!ticking) return;
    const interval = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(interval);
  }, [ticking]);
  const startedAt = Date.parse(turn.started_at);
  const completedAt = turn.completed_at === null ? now : Date.parse(turn.completed_at);
  return `Worked for ${formatDuration(Math.max(0, completedAt - startedAt))}`;
}

function TimelineItem({
  controller,
  entry,
  onAnnounce,
}: {
  controller: ChatConversationController;
  entry: TimelineEntry;
  onAnnounce: (message: string) => void;
}) {
  if (entry.kind === "user_input") {
    return (
      <article className="chat-message chat-message-user" data-entry-id={entry.entry_id}>
        <div className="chat-message-actions">
          <CopyTextButton content={entry.payload.content} label="Copy your message" onAnnounce={onAnnounce} />
        </div>
        <div className="chat-message-content">{entry.payload.content}</div>
        {entry.payload.source === "steer" ? <span className="chat-input-source">Steered</span> : null}
      </article>
    );
  }
  if (entry.kind === "assistant_message") {
    return (
      <article className="chat-message chat-message-assistant" data-entry-id={entry.entry_id}>
        <div className="chat-message-content">
          <AssistantMarkdown content={entry.payload.content} streaming={entry.payload.status === "streaming"} />
        </div>
        {entry.payload.status === "stopped" || entry.payload.status === "failed" ? (
          <span className={`chat-assistant-outcome chat-assistant-outcome-${entry.payload.status}`}>
            {entry.payload.status === "stopped" ? "Partial response · stopped" : "Partial response · failed"}
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
  const counts = entries.reduce((current, entry) => ({
    active: current.active + (entry.payload.status === "running" ? 1 : 0),
    failed: current.failed + (entry.payload.status === "failed" ? 1 : 0),
    stopped: current.stopped + (entry.payload.status === "stopped" ? 1 : 0),
  }), { active: 0, failed: 0, stopped: 0 });
  const details = [
    counts.active === 0 ? null : `${counts.active} active`,
    counts.failed === 0 ? null : `${counts.failed} failed`,
    counts.stopped === 0 ? null : `${counts.stopped} stopped`,
  ].filter((value): value is string => value !== null);
  return (
    <details className="chat-tool-group" data-entry-id={entries[0]?.entry_id}>
      <summary>
        <Wrench aria-hidden="true" size={15} />
        <span>{counts.active > 0 ? "Using" : "Used"} {entries.length} tool{entries.length === 1 ? "" : "s"}</span>
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
  const status = entry.payload.status;
  const Icon = status === "running"
    ? CircleNotch
    : status === "complete" ? CheckCircle : status === "stopped" ? StopCircle : WarningCircle;
  const label = status === "complete" ? "Completed" : status[0]?.toUpperCase() + status.slice(1);
  return (
    <li
      aria-label={`Tool ${entry.payload.name}: ${label}`}
      data-entry-id={entry.entry_id}
      data-tool-name={entry.payload.name}
      data-tool-status={status}
      role="article"
    >
      <Icon aria-hidden="true" className={status === "running" ? "chat-spinning" : undefined} size={14} />
      <code>{entry.payload.name}</code>
      <span>{label}</span>
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
  return (
    <section className="chat-question-activity" data-entry-id={entryId}>
      <details>
        <summary>
          <Question aria-hidden="true" size={16} />
          <span>{question.status === "answered" ? "Question answered" : question.status === "stopped" ? "Question stopped" : "Asking questions"}</span>
          <CaretDown aria-hidden="true" size={13} />
        </summary>
        <p>{question.question}</p>
      </details>
      {active ? <button className="chat-question-waiting" onClick={controller.focusComposer} type="button">
        <ListChecks aria-hidden="true" size={16} /><span>Waiting for your answer</span>
      </button> : null}
    </section>
  );
}

function TurnOutcome({ entry }: { entry: Extract<TimelineEntry, { kind: "turn_outcome" }> }) {
  if (entry.payload.status === "completed") {
    return <div aria-hidden="true" data-entry-id={entry.entry_id} data-turn-outcome="completed" />;
  }
  return (
    <div
      className={`chat-turn-outcome chat-turn-outcome-${entry.payload.status}`}
      data-entry-id={entry.entry_id}
      data-failure-code={entry.payload.errorCode}
      data-turn-outcome={entry.payload.status}
      role={entry.payload.status === "failed" ? "alert" : "status"}
    >
      {entry.payload.status === "stopped" ? <StopCircle aria-hidden="true" size={14} /> : <WarningCircle aria-hidden="true" size={14} />}
      <span>{entry.payload.status === "stopped" ? "Turn stopped" : "Turn failed"}</span>
      {entry.payload.errorCode === undefined ? null : <code>{entry.payload.errorCode}</code>}
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
  onAnnounce: (message: string) => void;
}) {
  const [copied, setCopied] = useState(false);
  async function copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      onAnnounce("Copied to clipboard.");
      window.setTimeout(() => setCopied(false), 1_500);
    } catch {
      onAnnounce("Could not copy to clipboard.");
    }
  }
  return (
    <button aria-label={label} disabled={content.length === 0} onClick={() => void copy()} type="button">
      {copied ? <Check aria-hidden="true" size={14} /> : <Copy aria-hidden="true" size={14} />}
      <span>Copy</span>
    </button>
  );
}

function formatDuration(milliseconds: number): string {
  const seconds = Math.floor(milliseconds / 1_000);
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return minutes === 0 ? `${remainingSeconds}s` : `${minutes}m ${remainingSeconds}s`;
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
  return (
    <section className="chat-empty-state">
      <span className="chat-empty-symbol" aria-hidden="true">α</span>
      <p className="eyebrow">Research Agent</p>
      <h1>Turn an investment idea into Alpha</h1>
      <p className="chat-empty-copy">
        Describe the signal you want to investigate. ThesisTrace will use the selected registered model and only this Chat's memory.
      </p>
      {opening ? <p className="chat-history-status">Opening conversation…</p> : null}
    </section>
  );
}
