import { Actions, Bubble, Think, ThoughtChain } from "@ant-design/x";
import XMarkdown, { type ComponentProps } from "@ant-design/x-markdown";
import "@ant-design/x-markdown/themes/dark.css";
import "./chatTypography.css";
import { Alert, Button, Card, Collapse, ConfigProvider, Divider, Flex, Typography } from "antd";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ArrowDown, ListChecks } from "@phosphor-icons/react";
import markedCjkFriendly from "marked-cjk-friendly";
import { i18n } from "../i18n";
import { formatNumber, formatTimestamp } from "../i18n/format";
import { parseResearchRunHref } from "./toolResult";
import { ResearchA2UIActivity } from "./researchA2UI";
import { chatViewMessages, projectChatEntries, WORK_ACTIVITY, ENTRY_ACTIVITY, type ChatViewMessage, type WorkContent, type EntryContent } from "./chatViewMessages";
import type { TimelineEntry, TimelineTurn, ChatQuestion } from "./chatProtocol";
import type { ChatConversationController } from "./useChatConversation";

const MESSAGE_TIME_FORMAT = new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit", hour12: true });
// X Markdown uses Marked 15: reuse the extension's CJK emphasis tokenizer.
// Its separate strikethrough tokenizer requires a newer Marked grammar.
const MARKDOWN_CONFIG = { tokenizer: { emStrong: markedCjkFriendly().tokenizer?.emStrong }, gfm: true, renderer: { html: () => "" } };
const MARKDOWN_COMPONENTS = { a: SafeMarkdownLink, img: HiddenMarkdownImage };
type ListItems = React.ComponentProps<typeof Bubble.List>["items"];
type ListRef = React.ComponentRef<typeof Bubble.List>;
type ChainItems = NonNullable<React.ComponentProps<typeof ThoughtChain>["items"]>;
type ToolActivity = Extract<TimelineEntry, { kind: "tool_activity" }>;
const TOOL_STATUS = { running: "loading", complete: "success", failed: "error", stopped: "abort" } as const;

/** Map the persisted timeline to official Ant Design X presentation components. */
export function ChatTimeline({ controller }: { controller: ChatConversationController }) {
  const { t } = useTranslation("chat");
  const list = useRef<ListRef>(null);
  const [readingOlder, setReadingOlder] = useState(false);
  const messages = chatViewMessages(controller.turns);
  const promptId = messages.filter(message => message.role === "user").at(-1)?.id;
  const running = controller.turns.at(-1)?.status === "running";
  const previousPrompt = useRef(promptId);
  const [anchoredPrompt, setAnchoredPrompt] = useState(running ? promptId : undefined);
  const [replySpace, setReplySpace] = useState(0);

  useLayoutEffect(() => {
    if (promptId !== previousPrompt.current) {
      // Hydrating completed history should retain the native latest position.
      if (previousPrompt.current !== undefined || running) setAnchoredPrompt(promptId);
      previousPrompt.current = promptId;
    }
  }, [promptId, running]);

  useLayoutEffect(() => {
    if (!anchoredPrompt) {
      setReplySpace(0);
      return;
    }
    let observer: ResizeObserver | undefined;
    let scrollFrame = 0;
    // Bubble.List initializes its scroll ref after mounting its native viewport.
    const setupFrame = requestAnimationFrame(() => {
      const viewport = list.current?.scrollBoxNativeElement;
      const prompt = Array.from(list.current?.nativeElement.querySelectorAll<HTMLElement>("[data-entry-id]") ?? [])
        .find(element => element.dataset.entryId === anchoredPrompt);
      const content = prompt?.parentElement;
      if (!viewport || !prompt || !content) return;
      const measureReplySpace = () => {
        const last = content.lastElementChild;
        if (!last) return;
        const turnHeight = last.getBoundingClientRect().bottom - prompt.getBoundingClientRect().top;
        const viewportInsets = Array.from(viewport.children)
          .filter(element => element !== content)
          .reduce((height, element) => height + element.getBoundingClientRect().height, 0);
        // Reserve only the room below this turn; streaming gradually uses it up.
        setReplySpace(Math.max(0, Math.round(viewport.clientHeight * 0.8 - viewportInsets - turnHeight)));
      };
      observer = new ResizeObserver(measureReplySpace);
      observer.observe(viewport);
      observer.observe(content);
      measureReplySpace();
      scrollFrame = requestAnimationFrame(() => list.current?.scrollTo({ key: anchoredPrompt, block: "start", behavior: "instant" }));
    });
    return () => {
      cancelAnimationFrame(setupFrame);
      cancelAnimationFrame(scrollFrame);
      observer?.disconnect();
    };
  }, [anchoredPrompt]);

  const items = bubbleItems(messages, controller);
  return <div className="relative flex min-h-0 flex-1 flex-col">
    <Bubble.List ref={list} className="min-h-0 flex-1"
      styles={{ scroll: { height: "100%", scrollbarGutter: "stable both-edges", scrollPaddingBlockStart: "20%" } }}
      items={items.map((item, index) => ({ ...item,
        style: { maxWidth: 808, marginInline: "auto", paddingInline: 20, paddingBlock: 8,
          marginBlockEnd: index === items.length - 1 ? replySpace : 0 },
      }))} autoScroll
      onScroll={() => setReadingOlder((list.current?.scrollBoxNativeElement.scrollTop ?? 0) < -80)} />
    {readingOlder ? <Button shape="round" className="absolute bottom-3 self-center" icon={<ArrowDown />} onClick={() => list.current?.scrollTo({ top: "bottom" })}>{t("backToLatest")}</Button> : null}
  </div>;
}

function bubbleItems(messages: readonly ChatViewMessage[], controller?: ChatConversationController): ListItems {
  return messages.flatMap((message): ListItems => {
    if (message.role === "tool") return [];
    const base = { key: message.id, role: "ai", variant: "borderless" as const, style: { paddingInline: 0 },
      "data-entry-id": message.id,
      classNames: { footer: "pointer-events-none opacity-0 group-hover/message:pointer-events-auto group-hover/message:opacity-100 group-focus-within/message:pointer-events-auto group-focus-within/message:opacity-100" },
      styles: { content: { padding: 0 }, body: { width: "100%" }, footer: { marginTop: 8 } } };
    if (message.role === "activity") return [{ ...base, role: "activity", content:
      message.activityType === WORK_ACTIVITY ? <WorkActivity content={message.content as WorkContent} controller={controller} />
      : message.activityType === ENTRY_ACTIVITY ? <EntryActivity content={message.content as EntryContent} controller={controller} />
      : <ResearchA2UIActivity message={message} /> }];
    if (message.role === "user") return [{ ...base, role: "user", placement: "end", variant: "filled", className: "chat-message-user group/message",
      styles: { body: { maxWidth: "85%" }, content: { whiteSpace: "pre-wrap" }, footer: base.styles.footer }, content: message.content,
      footerPlacement: "outer-end", footer: <MessageFooter message={message} user /> }];
    if (message.role !== "assistant") return [];
    return [{ ...base, className: "chat-message-assistant group/message", content: <>
      <AssistantMarkdown content={message.content ?? ""} streaming={message.entry?.kind === "assistant_message" && message.entry.payload.status === "streaming"} />
      <RecoveryNotice entry={message.entry} />
    </>, footerPlacement: "outer-start", footer: <MessageFooter message={message} /> }];
  });
}

function MessageFooter({ message, user = false }: { message: ChatViewMessage; user?: boolean }) {
  const label = user ? "Copy message" : "Copy response";
  // The official preset owns clipboard handling, keyboard interaction and feedback.
  const copy = <ConfigProvider locale={{ locale: "en", Text: { copy: label, copied: label } }}>
    <Actions.Copy text={typeof message.content === "string" ? message.content : ""} styles={{ root: { paddingInline: 0 } }} />
  </ConfigProvider>;
  const time = message.timestamp ? <Typography.Text type="secondary"><time dateTime={message.timestamp} title={formatTimestamp(message.timestamp, { dateStyle: "medium", timeStyle: "medium" })}>{MESSAGE_TIME_FORMAT.format(new Date(message.timestamp))}</time></Typography.Text> : null;
  return <Flex align="center" gap={8}>{user ? <>{time}{copy}</> : <>{copy}{time}</>}</Flex>;
}

function RecoveryNotice({ entry }: { entry?: TimelineEntry }) {
  const { t } = useTranslation("chat");
  const recovery = entry?.kind === "assistant_message" ? entry.payload.recovery : undefined;
  return recovery ? <Alert type="info" role="status" title={t(recovery.status === "recovering" ? "partialRecovering"
    : recovery.status === "succeeded" ? "partialReplaced" : recovery.attempts === 1 ? "partialRecoveryFailed"
    : recovery.cause === "OUTPUT_LIMIT" ? "partialOutputLimit" : "contextTooLarge")} /> : null;
}

function WorkActivity({ content, controller }: { content: WorkContent; controller?: ChatConversationController }) {
  const label = useWorkedFor({ turn: content.turn });
  return <Flex vertical gap={8}>
    <Think title={label} loading={content.turn.status === "running"} defaultExpanded={false}>
      {content.entries.length > 0 ? <WorkHistory entries={content.entries} controller={controller} /> : null}
    </Think>
    <Divider style={{ margin: 0 }} />
  </Flex>;
}

/** Map chronological product steps to the official connected chain and compact operations. */
function WorkHistory({ entries, controller }: { entries: readonly TimelineEntry[]; controller?: ChatConversationController }) {
  const { t } = useTranslation("chat");
  const messages = projectChatEntries(entries);
  const items: ChainItems = [];
  for (let index = 0; index < messages.length; index++) {
    const message = messages[index];
    if (message.role === "assistant") {
      items.push({ key: message.id, content: <div data-entry-id={message.id}>
        <AssistantMarkdown content={message.content ?? ""} streaming={message.entry?.kind === "assistant_message" && message.entry.payload.status === "streaming"} />
      </div> });
      continue;
    }
    if (message.role !== "activity" || message.activityType !== ENTRY_ACTIVITY) continue;
    const content = message.content as EntryContent;
    const entry = content.entry;
    if (entry.kind === "tool_activity") {
      const tools: ToolActivity[] = [entry];
      while (index + 1 < messages.length) {
        const next = messages[index + 1];
        if (next.role !== "activity" || next.activityType !== ENTRY_ACTIVITY) break;
        const nextEntry = (next.content as EntryContent).entry;
        if (nextEntry.kind !== "tool_activity") break;
        tools.push(nextEntry);
        index++;
      }
      const running = tools.some(tool => tool.payload.status === "running");
      const status = tools.some(tool => tool.payload.status === "failed") ? "error"
        : running ? "loading" : tools.some(tool => tool.payload.status === "stopped") ? "abort" : "success";
      items.push({ key: entry.entry_id, status, collapsible: true,
        title: t(running ? "usingTools" : "usedTools", { count: tools.length }),
        content: <Flex vertical gap="small" role="list">
          {tools.map(tool => <ToolOperation key={tool.entry_id} entry={tool} />)}
        </Flex>,
      });
    } else if (entry.kind === "question") {
      items.push({ key: entry.entry_id, status: entry.payload.status === "answered" ? "success"
        : entry.payload.status === "stopped" ? "abort" : "loading", collapsible: true,
        title: t(entry.payload.status === "answered" ? "questionAnswered" : entry.payload.status === "stopped" ? "questionStopped" : "askingQuestions"),
        content: <Flex gap="small" vertical>
          <Typography.Text type="secondary" style={{ whiteSpace: "pre-wrap" }}>{entry.payload.question}</Typography.Text>
          {content.answer ? <ThoughtChain.Item variant="solid" description={content.answer.content} /> : null}
        </Flex>,
      });
    } else {
      items.push({ key: entry.entry_id, content: <EntryActivity content={content} controller={controller} /> });
    }
  }
  const firstStep = items.find(item => item.collapsible)?.key;
  return <Card><ThoughtChain items={items}
    defaultExpandedKeys={firstStep === undefined ? [] : [firstStep]} /></Card>;
}

function ToolOperation({ entry }: { entry: ToolActivity }) {
  const { t } = useTranslation("chat");
  const statusLabel = t(`toolStatus.${entry.payload.status}`);
  return <ThoughtChain.Item variant="solid" status={TOOL_STATUS[entry.payload.status]}
    title={entry.payload.name} description={statusLabel} role="listitem" data-entry-id={entry.entry_id}
    aria-label={t("toolAria", { name: entry.payload.name, status: statusLabel })} />;
}

function EntryActivity({ content, controller }: { content: EntryContent; controller?: ChatConversationController }) {
  const entry = content.entry;
  if (entry.kind === "tool_activity") return <ToolOperation entry={entry} />;
  if (entry.kind === "question") return <>
    <QuestionSurface active={entry.payload.status === "pending"} controller={controller} entryId={entry.entry_id} question={entry.payload} />
    {content.answer ? <ThoughtChain.Item variant="solid" description={content.answer.content} /> : null}
  </>;
  return entry.kind === "turn_outcome" ? <TurnOutcome entry={entry} /> : null;
}

function useWorkedFor({ turn }: { turn: TimelineTurn }) {
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


function formatDuration(milliseconds: number): string {
  const seconds = Math.floor(milliseconds / 1_000);
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return minutes === 0
    ? i18n.t("chat:durationSeconds", { seconds: formatNumber(remainingSeconds) })
    : i18n.t("chat:durationMinutes", { minutes: formatNumber(minutes), seconds: formatNumber(remainingSeconds) });
}


function QuestionSurface({
  active,
  controller,
  entryId,
  question,
}: {
  active: boolean;
  controller?: ChatConversationController;
  entryId: string;
  question: ChatQuestion & Readonly<{ status: "pending" | "answered" | "stopped" }>;
}) {
  const { t } = useTranslation("chat");
  return (
    <section className="chat-question-activity grid min-w-0 gap-2" data-entry-id={entryId}>
      <Collapse ghost items={[{ key: entryId,
        label: t(question.status === "answered" ? "questionAnswered" : question.status === "stopped" ? "questionStopped" : "askingQuestions"),
        forceRender: true, children: <Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>{question.question}</Typography.Paragraph>,
      }]} />
      {active ? <Button type="text" className="chat-question-waiting" icon={<ListChecks />} onClick={controller?.focusComposer}>{t("waitingAnswer")}</Button> : null}
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
    <Alert type={entry.payload.status === "failed" ? "error" : "warning"} showIcon
      data-entry-id={entry.entry_id}
      data-failure-code={entry.payload.errorCode}
      data-turn-outcome={entry.payload.status}
      role={entry.payload.status === "failed" ? "alert" : "status"}
      title={explanationCode === null ? <>
        <Typography.Text>{t(entry.payload.status === "stopped" ? "turnStopped" : "turnFailed")}</Typography.Text>
        {entry.payload.errorCode === undefined ? null : <Typography.Text code>{entry.payload.errorCode}</Typography.Text>}
      </> : t(`agentFailures.${explanationCode}.label`)}
      description={explanationCode === null ? undefined : t(`agentFailures.${explanationCode}.message`)} />
  );
}


export function AssistantMarkdown({ content, streaming = false }: { content: string; streaming?: boolean }) {
  return <XMarkdown content={content} config={MARKDOWN_CONFIG} components={MARKDOWN_COMPONENTS}
    className="x-markdown-dark chat-markdown-reading" streaming={{ hasNextChunk: streaming }} />;
}

function SafeMarkdownLink({ children, href }: ComponentProps) {
  const safeHref = parseResearchRunHref(typeof href === "string" ? href : undefined);
  return safeHref === null ? <Typography.Text className="chat-markdown-link-disabled" type="secondary">{children}</Typography.Text>
    : <Typography.Link className="chat-markdown-run-link" href={safeHref}>{children}</Typography.Link>;
}

function HiddenMarkdownImage() { return null; }
