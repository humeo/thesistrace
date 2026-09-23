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
    <form className="chat-composer-dock" onSubmit={submit}>
      {controller.queue.length === 0 ? null : (
        <StagedQueue
          controller={controller}
          expanded={queueExpanded}
          onToggle={() => setQueueExpanded((current) => !current)}
        />
      )}
      {controller.error === null ? null : (
        <div
          className="chat-run-error"
          data-failure-code={controller.errorCode ?? undefined}
          role="alert"
        >
          <span>{controller.error}</span>
          <button className="button-quiet" onClick={() => void controller.retryRecovery()} type="button">{t("retry")}</button>
        </div>
      )}
      {tooLarge ? <p className="chat-composer-validation" id="chat-composer-validation">{t("inputTooLarge")}</p> : null}
      {question !== null ? (
        <QuestionComposer controller={controller} question={question} locked={interactionLocked}
          tooLarge={tooLarge} onKeyDown={keyDown} />
      ) : <div className={`chat-composer-surface${interactionLocked ? " chat-composer-surface-locked" : ""}`}>
        <textarea
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
        <div className="chat-composer-toolbar">
          {controller.draftBytes < MAX_CHAT_MESSAGE_BYTES * .8 ? null : (
            <span className={`chat-byte-count${tooLarge ? " chat-byte-count-invalid" : ""}`}>
              {t("byteCount", { current: formatNumber(controller.draftBytes), limit: formatNumber(MAX_CHAT_MESSAGE_BYTES) })}
            </span>
          )}
          <div className="chat-composer-toolbar-actions">
            {modelControls}
            <button
              aria-label={t(actionLabelKey(controller.action.kind, controller.phase))}
              className={`chat-main-action chat-main-action-${controller.action.kind}`}
              disabled={!controller.action.enabled}
              type="submit"
            >
              <MainActionIcon kind={controller.action.kind} />
            </button>
          </div>
        </div>
      </div>}
      {question !== null && controller.draftBytes >= MAX_CHAT_MESSAGE_BYTES * .8 ? (
        <span className={`chat-byte-count${tooLarge ? " chat-byte-count-invalid" : ""}`}>
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
    <section aria-label={t("stagedInputs")} className="chat-staged-queue">
      <button aria-expanded={expanded} className="chat-staged-heading" onClick={onToggle} type="button">
        <span>{t("stagedInputs")}</span>
        <span>{formatNumber(controller.queue.length)}</span>
        <CaretDown aria-hidden="true" className={expanded ? "chat-caret-open" : undefined} size={14} />
      </button>
      {!expanded ? null : (
        <ol>
          {controller.queue.map((item, index) => (
            <StagedQueueItem controller={controller} head={index === 0} item={item} key={item.inputId} />
          ))}
        </ol>
      )}
    </section>
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
    <li className={item.status === "submitting" ? "chat-staged-submitting" : undefined}>
      <details>
        <summary>
          <span className="chat-staged-position">{t(head ? "next" : "queued")}</span>
          <span className="chat-staged-preview">{oneLine(item.content)}</span>
          <span className="chat-staged-state">{t(item.status === "submitting" ? "submitting" : "staged")}</span>
        </summary>
        <p>{item.content}</p>
      </details>
      <div className="chat-staged-actions">
        {head && controller.phase === "active" ? (
          <button disabled={locked} onClick={() => void controller.steerStaged(item)} type="button">{t("steer")}</button>
        ) : null}
        <button
          aria-label={t("editStaged")}
          disabled={locked || controller.question !== null || controller.draft.length !== 0}
          onClick={() => void controller.editStaged(item)}
          title={t(controller.question !== null ? "finishAnswerFirst"
            : controller.draft.length === 0 ? "edit" : "clearDraftFirst")}
          type="button"
        >
          <PencilSimple aria-hidden="true" size={14} />
        </button>
        <button aria-label={t("deleteStaged")} disabled={locked} onClick={() => void controller.removeStaged(item)} type="button">
          <Trash aria-hidden="true" size={14} />
        </button>
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
