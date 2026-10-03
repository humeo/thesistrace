import { Sender } from "@ant-design/x";
import { Alert, Button, Collapse, Flex, Tag, Typography } from "antd";
import {
  PencilSimple,
  Trash,
} from "@phosphor-icons/react";
import { useState, type FormEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { formatNumber } from "../i18n/format";

import { QuestionComposer } from "./QuestionComposer";
import type { StagedInput } from "./stagedInputStore";
import type { ChatConversationController } from "./useChatConversation";

const MAX_CHAT_MESSAGE_BYTES = 16 * 1024;

export function ChatComposer({
  controller,
  modelControls,
}: {
  controller: ChatConversationController;
  modelControls: ReactNode;
}) {
  const { t } = useTranslation("chat");
  const question = controller.question;
  const interactionLocked = ["opening", "stopping", "recovering"].includes(controller.phase);
  const tooLarge = controller.draftBytes > MAX_CHAT_MESSAGE_BYTES;
  const [queueExpanded, setQueueExpanded] = useState(true);


  function submit(event: FormEvent): void {
    event.preventDefault();
    if (question !== null && controller.action.kind !== "answer") return;
    void controller.executeMainAction();
  }

  return (
    <form className="w-full shrink-0 pointer-events-auto" onSubmit={submit}>
      {controller.queue.length === 0 ? null : (
        <StagedQueue
          controller={controller}
          expanded={queueExpanded}
          onToggle={() => setQueueExpanded((current) => !current)}
        />
      )}
      {controller.error === null ? null : (
        <Alert type="error"
          className="chat-run-error mb-3"
          data-failure-code={controller.errorCode ?? undefined}
          role="alert" title={controller.error}
          action={<Button type="text" onClick={() => void controller.retryRecovery()}>{t("retry")}</Button>} />
      )}
      {tooLarge ? <Typography.Paragraph type="danger" className="chat-composer-validation" id="chat-composer-validation">{t("inputTooLarge")}</Typography.Paragraph> : null}
      {question !== null ? (
        <QuestionComposer controller={controller} question={question} locked={interactionLocked}
          tooLarge={tooLarge} />
      ) : <Sender value={controller.draft} loading={controller.action.kind === "stop"}
        ref={instance => { controller.textareaRef.current = instance?.inputElement as HTMLTextAreaElement | null; }}
        aria-label={t("message")} aria-invalid={tooLarge || undefined} aria-describedby="chat-composer-guidance"
        disabled={interactionLocked} placeholder={t(controller.phase === "active" ? "activePlaceholder" : "newPlaceholder")}
        onSubmit={() => { if (controller.action.enabled) void controller.executeMainAction(); }}
        onChange={controller.setDraft} onCancel={() => void controller.executeMainAction()}
        autoSize={{ minRows: 2, maxRows: 8 }} suffix={false}
        footer={(_, { components: { SendButton, LoadingButton } }) => <Flex align="center" justify="space-between" gap={8}>
          {modelControls}
          {controller.action.kind === "stop" ? <LoadingButton aria-label={t("stop")} disabled={!controller.action.enabled} />
            : <SendButton aria-label={t(actionLabelKey(controller.action.kind, controller.phase))} disabled={!controller.action.enabled} />}
        </Flex>} />}
      {question !== null && controller.draftBytes >= MAX_CHAT_MESSAGE_BYTES * .8 ? (
        <Typography.Text className="chat-byte-count" type={tooLarge ? "danger" : "secondary"}>
          {t("byteCount", { current: formatNumber(controller.draftBytes), limit: formatNumber(MAX_CHAT_MESSAGE_BYTES) })}
        </Typography.Text>
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
        {controller.statusAnnouncement}
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
    <Collapse className="chat-staged-queue" style={{ marginBottom: 12 }} activeKey={expanded ? ["queue"] : []}
      onChange={onToggle} items={[{ key: "queue", forceRender: true,
        label: <Flex align="center" gap={8}>{t("stagedInputs")}<Tag>{formatNumber(controller.queue.length)}</Tag></Flex>,
        children: <Flex vertical style={{ maxHeight: "min(230px,28dvh)", overflowY: "auto" }}>
          {controller.queue.map((item, index) => <StagedQueueItem controller={controller} head={index === 0} item={item} key={item.inputId} />)}
        </Flex>,
      }]} />
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
    <Collapse ghost data-staged-input={item.inputId} items={[{ key: item.inputId, forceRender: true,
      label: <Flex align="center" gap={8}>
        <Tag>{t(head ? "next" : "queued")}</Tag>
        <Typography.Text ellipsis style={{ maxWidth: 320 }}>{oneLine(item.content)}</Typography.Text>
        <Tag>{t(item.status === "submitting" ? "submitting" : "staged")}</Tag>
      </Flex>, children: <Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>{item.content}</Typography.Paragraph>,
      extra: <Flex className="chat-staged-actions" gap={4} onClick={event => event.stopPropagation()}>
        {head && controller.phase === "active" ? (
          <Button disabled={locked} onClick={() => void controller.steerStaged(item)}>{t("steer")}</Button>
        ) : null}
        <Button
          type="text" icon={<PencilSimple />} aria-label={t("editStaged")}
          disabled={locked || controller.question !== null || controller.draft.length !== 0}
          onClick={() => void controller.editStaged(item)}
          title={t(controller.question !== null ? "finishAnswerFirst"
            : controller.draft.length === 0 ? "edit" : "clearDraftFirst")}
        />
        <Button type="text" icon={<Trash />} aria-label={t("deleteStaged")} disabled={locked} onClick={() => void controller.removeStaged(item)} />
      </Flex>,
    }]} />
  );
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
