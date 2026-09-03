import type { ActivityMessage } from "@ag-ui/core";
import {
  ArrowDown,
  Check,
  CheckCircle,
  CircleNotch,
  Copy,
  StopCircle,
  WarningCircle,
} from "@phosphor-icons/react";
import {
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { parseResearchRunHref } from "./toolResult";
import { ResearchA2UIActivity } from "./researchA2UI";
import type { ChatConversationController } from "./useChatConversation";
import type { ChatQuestion, TimelineEntry } from "./chatProtocol";

const BOTTOM_THRESHOLD_PX = 24;
const RESEARCH_MARKDOWN_REMARK_PLUGINS = [remarkGfm];

type ScrollAnchor = Readonly<{ entryId: string; top: number }>;

export function ChatTimeline({
  controller,
  onAnnounce,
}: {
  controller: ChatConversationController;
  onAnnounce: (message: string) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const previousScrollTopRef = useRef(0);
  const touchYRef = useRef<number | null>(null);
  const anchorRef = useRef<ScrollAnchor | null>(null);
  const initialPositionedRef = useRef(false);
  const [following, setFollowing] = useState(true);

  useLayoutEffect(() => {
    const viewport = scrollRef.current;
    if (viewport === null) return;
    const anchor = anchorRef.current;
    if (anchor !== null) {
      const target = [...viewport.querySelectorAll<HTMLElement>("[data-entry-id]")]
        .find((element) => element.dataset.entryId === anchor.entryId);
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
  }, [controller.timeline, following]);

  async function loadOlder(): Promise<void> {
    const viewport = scrollRef.current;
    if (viewport === null) return;
    const viewportBounds = viewport.getBoundingClientRect();
    const first = [
      ...viewport.querySelectorAll<HTMLElement>("[data-entry-id]"),
    ].find((element) => {
      const bounds = element.getBoundingClientRect();
      return bounds.bottom > viewportBounds.top && bounds.top < viewportBounds.bottom;
    });
    if (first !== undefined) {
      anchorRef.current = { entryId: first.dataset.entryId ?? "", top: first.getBoundingClientRect().top };
    }
    const loaded = await controller.loadOlder();
    if (!loaded) anchorRef.current = null;
  }

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

  const empty = controller.timeline.length === 0;
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
        {controller.nextCursor === null ? null : (
          <button
            className="chat-timeline-load-older button-quiet"
            disabled={controller.loadingOlder}
            onClick={() => void loadOlder()}
            type="button"
          >
            {controller.loadingOlder ? "Loading earlier messages…" : "Load earlier messages"}
          </button>
        )}
        {controller.timelineError ? (
          <div className="chat-timeline-error">
            <span>Conversation history could not be updated.</span>
            <button className="button-quiet" onClick={() => void controller.refresh()} type="button">Retry</button>
          </div>
        ) : null}
        {empty ? <ChatIntroduction opening={controller.phase === "opening"} /> : (
          <div className="chat-timeline-content">
            {controller.timeline.map((entry) => (
              <TimelineItem
                controller={controller}
                entry={entry}
                key={entry.entry_id}
                onAnnounce={onAnnounce}
              />
            ))}
            {controller.phase === "active" && !controller.hasFirstAssistantText ? (
              <div aria-label="Research Agent is preparing a response" className="chat-response-indicator">
                <span aria-hidden="true" />
                <span>Working</span>
              </div>
            ) : null}
          </div>
        )}
        <div aria-hidden="true" className="chat-bottom-sentinel" ref={sentinelRef} />
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
        <div className="chat-message-actions">
          <CopyTextButton content={entry.payload.content} label="Copy response" onAnnounce={onAnnounce} />
        </div>
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
  if (entry.kind === "tool_activity") {
    return <ToolActivityRow entry={entry} />;
  }
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
        controller={controller}
        entryId={entry.entry_id}
        question={entry.payload}
        active={active}
      />
    );
  }
  return <TurnOutcome entry={entry} />;
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
    <section className={`chat-question${active ? " chat-question-active" : ""}`} data-entry-id={entryId}>
      <span className="chat-question-kicker">Input required</span>
      <h2>{question.question}</h2>
      {!active || question.options === null ? null : (
        <fieldset>
          <legend>{question.selection_mode === "multi_select" ? "Select all that apply" : "Select one"}</legend>
          {question.options.map((option) => {
            const selected = controller.answerSelections.includes(option.label);
            return (
              <label key={option.label}>
                <input
                  checked={selected}
                  name={`question-${question.interrupt_id}`}
                  onChange={() => {
                    controller.setAnswerSelections(question.selection_mode === "multi_select"
                      ? selected
                        ? controller.answerSelections.filter((value) => value !== option.label)
                        : [...controller.answerSelections, option.label]
                      : [option.label]);
                  }}
                  type={question.selection_mode === "multi_select" ? "checkbox" : "radio"}
                  value={option.label}
                />
                <span>
                  <strong>{option.label}</strong>
                  {option.description === undefined ? null : <small>{option.description}</small>}
                </span>
              </label>
            );
          })}
        </fieldset>
      )}
      {active && question.selection_mode === "free_text" ? (
        <p className="chat-question-hint">Type your answer below, then send it to continue this Turn.</p>
      ) : null}
      {!active ? <span className="chat-question-resolution">{question.status === "answered" ? "Answered" : "Stopped"}</span> : null}
    </section>
  );
}

function ToolActivityRow({ entry }: { entry: Extract<TimelineEntry, { kind: "tool_activity" }> }) {
  const status = entry.payload.status;
  const Icon = status === "running"
    ? CircleNotch
    : status === "complete" ? CheckCircle : status === "stopped" ? StopCircle : WarningCircle;
  const label = status === "complete" ? "Completed" : status[0]?.toUpperCase() + status.slice(1);
  return (
    <article aria-label={`Tool ${entry.payload.name}: ${label}`} className={`chat-tool-activity chat-tool-activity-${status}`} data-entry-id={entry.entry_id}>
      <Icon aria-hidden="true" size={15} />
      <span className="chat-tool-kind">Tool</span>
      <code>{entry.payload.name}</code>
      <span className="chat-tool-status">{label}</span>
    </article>
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
