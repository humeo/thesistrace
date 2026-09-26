import { cn } from "cn";
import styles from "./ChatLayout.module.css";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "../components/ui/collapsible";
import {
  ArrowClockwise,
  ArrowUp,
  CaretDown,
  PencilSimple,
  Stop,
  Trash,
} from "@phosphor-icons/react";
import { useLayoutEffect, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { formatNumber } from "../i18n/format";

import { shouldSubmitFromEnter } from "./chatState";
import { QuestionComposer } from "./QuestionComposer";
import type { StagedInput } from "./stagedInputStore";
import type { ChatConversationController } from "./useChatConversation";

const MAX_CHAT_MESSAGE_BYTES = 16 * 1024;

export function ChatComposer({
  announcement,
  controller,
  modelControls,
}: {
  announcement: string;
  controller: ChatConversationController;
  modelControls: ReactNode;
}) {
  const { t } = useTranslation("chat");
  const question = controller.question;
  const interactionLocked = ["opening", "stopping", "recovering"].includes(controller.phase);
  const tooLarge = controller.draftBytes > MAX_CHAT_MESSAGE_BYTES;
  const [queueExpanded, setQueueExpanded] = useState(true);

  useLayoutEffect(() => {
    const textarea = controller.textareaRef.current;
    if (textarea === null) return;
    textarea.style.height = "auto";
    // CSS owns the responsive maximum and scrolling; resetting height first
    // also lets the composer shrink when text or blank lines are removed.
    textarea.style.height = `${textarea.scrollHeight}px`;
  }, [controller.draft, controller.textareaRef, question?.interrupt_id]);

  function submit(event: FormEvent): void {
    event.preventDefault();
    if (question !== null && controller.action.kind !== "answer") return;
    void controller.executeMainAction();
  }

  function keyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (!shouldSubmitFromEnter({
      action: controller.action,
      composing: event.nativeEvent.isComposing,
      key: event.key,
      shiftKey: event.shiftKey,
    })) return;
    event.preventDefault();
    void controller.executeMainAction();
  }

  return (
    <form className={cn("chat-composer-dock", styles.dock)} onSubmit={submit}>
      {controller.queue.length === 0 ? null : (
        <StagedQueue
          controller={controller}
          expanded={queueExpanded}
          onToggle={() => setQueueExpanded((current) => !current)}
        />
      )}
      {controller.error === null ? null : (
        <div
          className="chat-run-error mb-3 flex items-center justify-between gap-3 rounded-lg border border-destructive p-3 text-sm text-destructive"
          data-failure-code={controller.errorCode ?? undefined}
          role="alert"
        >
          <span>{controller.error}</span>
          <Button variant="ghost" onClick={() => void controller.retryRecovery()} type="button">{t("retry")}</Button>
        </div>
      )}
      {tooLarge ? <p className="chat-composer-validation my-2 text-xs text-destructive" id="chat-composer-validation">{t("inputTooLarge")}</p> : null}
      {question !== null ? (
        <QuestionComposer controller={controller} question={question} locked={interactionLocked}
          tooLarge={tooLarge} onKeyDown={keyDown} />
      ) : <div className={cn("chat-composer-surface", styles.surface, interactionLocked && "opacity-60")}>
        <Textarea className={styles.input}
          aria-describedby={tooLarge ? "chat-composer-guidance chat-composer-validation" : "chat-composer-guidance"}
          aria-invalid={tooLarge || undefined}
          aria-label={t("message")}
          disabled={interactionLocked}
          onChange={(event) => controller.setDraft(event.target.value)}
          onKeyDown={keyDown}
          placeholder={t(controller.phase === "active" ? "activePlaceholder" : "newPlaceholder")}
          ref={controller.textareaRef}
          rows={2}
          value={controller.draft}
        />
        <div className="chat-composer-toolbar flex min-h-12 items-center justify-between gap-3 px-3 pb-2">
          {controller.draftBytes < MAX_CHAT_MESSAGE_BYTES * .8 ? null : (
            <span className={cn("chat-byte-count whitespace-nowrap text-xs", tooLarge ? "text-destructive" : "text-muted-foreground")}>
              {t("byteCount", { current: formatNumber(controller.draftBytes), limit: formatNumber(MAX_CHAT_MESSAGE_BYTES) })}
            </span>
          )}
          <div className="chat-composer-toolbar-actions ml-auto flex min-w-0 items-center gap-2">
            {modelControls}
            <Button
              aria-label={t(actionLabelKey(controller.action.kind, controller.phase))}
              className="chat-main-action" size="icon"
              disabled={!controller.action.enabled}
              type="submit"
            >
              <MainActionIcon kind={controller.action.kind} />
            </Button>
          </div>
        </div>
      </div>}
      {question !== null && controller.draftBytes >= MAX_CHAT_MESSAGE_BYTES * .8 ? (
        <span className={cn("chat-byte-count whitespace-nowrap text-xs", tooLarge ? "text-destructive" : "text-muted-foreground")}>
          {t("byteCount", { current: formatNumber(controller.draftBytes), limit: formatNumber(MAX_CHAT_MESSAGE_BYTES) })}
        </span>
      ) : null}
      <div className="visually-hidden" id="chat-composer-guidance">
        <span>{t("enterGuidance", { action: t(question !== null ? "enterAnswer" : enterActionLabel(controller.action.kind, controller.phase)) })} </span>
        <span>{question !== null
          ? t("continuesTurn")
          : controller.phase === "active"
          ? t("nextTurnSettings")
          : t("textOnly")}</span>
      </div>
      <span aria-hidden="true" className="visually-hidden" data-chat-status>
        {t(phaseLabel(controller.phase, controller.latestTurnStatus))}
      </span>
      <div aria-atomic="true" aria-live="polite" className="visually-hidden">
        {announcement || controller.statusAnnouncement}
      </div>
    </form>
  );
}

function StagedQueue({
  controller,
  expanded,
  onToggle,
}: {
  controller: ChatConversationController;
  expanded: boolean;
  onToggle: () => void;
}) {
  const { t } = useTranslation("chat");
  return (
    <Collapsible open={expanded} onOpenChange={onToggle} aria-label={t("stagedInputs")} className="chat-staged-queue mb-3 overflow-hidden rounded-lg border border-border bg-card">
      <CollapsibleTrigger render={<Button variant="ghost" className="chat-staged-heading min-h-11 w-full justify-between" />} >
        <span>{t("stagedInputs")}</span>
        <span>{formatNumber(controller.queue.length)}</span>
        <CaretDown aria-hidden="true" className={cn(expanded && "rotate-180")} size={14} />
      </CollapsibleTrigger>
      <CollapsibleContent keepMounted>
        <ol className="m-0 grid max-h-[min(230px,28dvh)] list-none overflow-y-auto border-t border-border p-0">
          {controller.queue.map((item, index) => (
            <StagedQueueItem controller={controller} head={index === 0} item={item} key={item.inputId} />
          ))}
        </ol>
      </CollapsibleContent>
    </Collapsible>
  );
}

function StagedQueueItem({
  controller,
  head,
  item,
}: {
  controller: ChatConversationController;
  head: boolean;
  item: StagedInput;
}) {
  const { t } = useTranslation("chat");
  const locked = controller.queueLocked || item.status === "submitting";
  return (
    <li className={cn("grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-start gap-2 p-2", item.status === "submitting" && "opacity-60")}>
      <Collapsible className="min-w-0">
        <CollapsibleTrigger render={<Button variant="ghost" className="min-h-11 w-full justify-start gap-2 text-left" />}>
          <span className="chat-staged-position text-xs text-muted-foreground">{t(head ? "next" : "queued")}</span>
          <span className="chat-staged-preview min-w-0 truncate">{oneLine(item.content)}</span>
          <span className="chat-staged-state text-xs text-muted-foreground">{t(item.status === "submitting" ? "submitting" : "staged")}</span>
        </CollapsibleTrigger>
        <CollapsibleContent keepMounted className="px-2 pb-2 text-sm whitespace-pre-wrap [overflow-wrap:anywhere]">{item.content}</CollapsibleContent>
      </Collapsible>
      <div className="chat-staged-actions flex items-center gap-1">
        {head && controller.phase === "active" ? (
          <Button variant="outline" disabled={locked} onClick={() => void controller.steerStaged(item)} type="button">{t("steer")}</Button>
        ) : null}
        <Button
          variant="ghost" size="icon" aria-label={t("editStaged")}
          disabled={locked || controller.question !== null || controller.draft.length !== 0}
          onClick={() => void controller.editStaged(item)}
          title={t(controller.question !== null ? "finishAnswerFirst"
            : controller.draft.length === 0 ? "edit" : "clearDraftFirst")}
          type="button"
        >
          <PencilSimple aria-hidden="true" size={14} />
        </Button>
        <Button variant="ghost" size="icon" aria-label={t("deleteStaged")} disabled={locked} onClick={() => void controller.removeStaged(item)} type="button">
          <Trash aria-hidden="true" size={14} />
        </Button>
      </div>
    </li>
  );
}

function MainActionIcon({ kind }: { kind: ChatConversationController["action"]["kind"] }) {
  if (kind === "stop") return <Stop aria-hidden="true" size={17} weight="fill" />;
  if (kind === "continue") return <ArrowClockwise aria-hidden="true" size={18} weight="bold" />;
  return <ArrowUp aria-hidden="true" size={18} weight="bold" />;
}

function actionLabelKey(kind: ChatConversationController["action"]["kind"], phase: ChatConversationController["phase"]): "stop" | "stage" | "answer" | "stopping" | "opening" | "recovering" | "continue" | "send" {
  if (phase === "stopping") return "stopping";
  if (phase === "opening") return "opening";
  if (phase === "recovering") return "recovering";
  return kind;
}

function enterActionLabel(
  kind: ChatConversationController["action"]["kind"],
  phase: ChatConversationController["phase"],
): "enterStage" | "enterAnswer" | "enterSend" {
  if (kind === "stage" || phase === "active") return "enterStage";
  if (kind === "answer" || phase === "waiting_for_user") return "enterAnswer";
  return "enterSend";
}

function phaseLabel(
  phase: ChatConversationController["phase"],
  latestTurnStatus: ChatConversationController["latestTurnStatus"],
): "phaseLabels.new" | "phaseLabels.opening" | "phaseLabels.complete" | "phaseLabels.failed" | "phaseLabels.stopped" | "phaseLabels.ready" | "phaseLabels.active" | "phaseLabels.waiting" | "phaseLabels.stopping" | "phaseLabels.recovering" {
  switch (phase) {
    case "new": return "phaseLabels.new";
    case "opening": return "phaseLabels.opening";
    case "idle": return latestTurnStatus === "completed"
      ? "phaseLabels.complete"
      : latestTurnStatus === "failed"
        ? "phaseLabels.failed"
        : latestTurnStatus === "stopped" ? "phaseLabels.stopped" : "phaseLabels.ready";
    case "active": return "phaseLabels.active";
    case "waiting_for_user": return "phaseLabels.waiting";
    case "stopping": return "phaseLabels.stopping";
    case "recovering": return "phaseLabels.recovering";
  }
}

function oneLine(value: string): string {
  return value.replace(/\s+/gu, " ").trim();
}
