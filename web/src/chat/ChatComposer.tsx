import {
  ArrowClockwise,
  ArrowUp,
  CaretDown,
  PencilSimple,
  Stop,
  Trash,
} from "@phosphor-icons/react";
import { useLayoutEffect, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";

import { shouldSubmitFromEnter } from "./chatState";
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
  const selectionQuestion = controller.phase === "waiting_for_user"
    && controller.question?.selection_mode !== "free_text";
  const interactionLocked = ["opening", "stopping", "recovering"].includes(controller.phase);
  const tooLarge = controller.draftBytes > MAX_CHAT_MESSAGE_BYTES;
  const [queueExpanded, setQueueExpanded] = useState(true);

  useLayoutEffect(() => {
    const textarea = controller.textareaRef.current;
    if (textarea === null) return;
    textarea.style.height = "auto";
    const maxHeight = window.innerHeight * (window.matchMedia("(max-width: 768px)").matches ? 0.32 : 0.4);
    textarea.style.height = `${Math.min(textarea.scrollHeight, maxHeight)}px`;
    textarea.style.overflowY = textarea.scrollHeight > maxHeight ? "auto" : "hidden";
  }, [controller.draft, controller.textareaRef]);

  function submit(event: FormEvent): void {
    event.preventDefault();
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
          <button className="button-quiet" onClick={() => void controller.retryRecovery()} type="button">Retry</button>
        </div>
      )}
      {tooLarge ? <p className="chat-composer-validation" id="chat-composer-validation">Input exceeds the 16 KiB limit.</p> : null}
      <div className={`chat-composer-surface${interactionLocked ? " chat-composer-surface-locked" : ""}`}>
        <textarea
          aria-describedby={tooLarge ? "chat-composer-guidance chat-composer-validation" : "chat-composer-guidance"}
          aria-invalid={tooLarge || undefined}
          aria-label={controller.phase === "waiting_for_user" ? "Answer" : "Message"}
          disabled={interactionLocked || selectionQuestion}
          onChange={(event) => controller.setDraft(event.target.value)}
          onKeyDown={keyDown}
          placeholder={selectionQuestion
            ? "Select an answer in the question above"
            : controller.phase === "waiting_for_user"
              ? "Type your answer…"
              : controller.phase === "active" ? "Steer this Turn or write the next prompt…" : "Ask about an investment idea…"}
          ref={controller.textareaRef}
          rows={2}
          value={controller.draft}
        />
        <div className="chat-composer-toolbar">
          {controller.draftBytes < MAX_CHAT_MESSAGE_BYTES * .8 ? null : (
            <span className={`chat-byte-count${tooLarge ? " chat-byte-count-invalid" : ""}`}>
              {controller.draftBytes.toLocaleString()} / {MAX_CHAT_MESSAGE_BYTES.toLocaleString()} bytes
            </span>
          )}
          <div className="chat-composer-toolbar-actions">
            {modelControls}
            <button
              aria-label={controller.action.label}
              className={`chat-main-action chat-main-action-${controller.action.kind}`}
              disabled={!controller.action.enabled}
              type="submit"
            >
              <MainActionIcon kind={controller.action.kind} />
            </button>
          </div>
        </div>
      </div>
      <div className="chat-composer-guidance" id="chat-composer-guidance">
        <span>Enter to {enterActionLabel(controller.action.kind, controller.phase)} · Shift+Enter for newline</span>
        <span>{controller.phase === "active" || controller.phase === "waiting_for_user"
          ? "Settings apply to the next new Turn"
          : "Text only"}</span>
      </div>
      <span aria-hidden="true" className="visually-hidden" data-chat-status>
        {phaseLabel(controller.phase, controller.latestTurnStatus)}
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
  return (
    <section aria-label="Staged inputs" className="chat-staged-queue">
      <button aria-expanded={expanded} className="chat-staged-heading" onClick={onToggle} type="button">
        <span>Staged inputs</span>
        <span>{controller.queue.length}</span>
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
  const locked = controller.queueLocked || item.status === "submitting";
  return (
    <li className={item.status === "submitting" ? "chat-staged-submitting" : undefined}>
      <details>
        <summary>
          <span className="chat-staged-position">{head ? "Next" : "Queued"}</span>
          <span className="chat-staged-preview">{oneLine(item.content)}</span>
          <span className="chat-staged-state">{item.status === "submitting" ? "Submitting" : "Staged"}</span>
        </summary>
        <p>{item.content}</p>
      </details>
      <div className="chat-staged-actions">
        {head && controller.phase === "active" ? (
          <button disabled={locked} onClick={() => void controller.steerStaged(item)} type="button">Steer</button>
        ) : null}
        <button
          aria-label="Edit staged input"
          disabled={locked || controller.draft.length !== 0}
          onClick={() => void controller.editStaged(item)}
          title={controller.draft.length === 0 ? "Edit" : "Clear the draft before editing"}
          type="button"
        >
          <PencilSimple aria-hidden="true" size={14} />
        </button>
        <button aria-label="Delete staged input" disabled={locked} onClick={() => void controller.removeStaged(item)} type="button">
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

function enterActionLabel(
  kind: ChatConversationController["action"]["kind"],
  phase: ChatConversationController["phase"],
): string {
  if (kind === "stage" || phase === "active") return "stage";
  if (kind === "answer" || phase === "waiting_for_user") return "answer";
  return "send";
}

function phaseLabel(
  phase: ChatConversationController["phase"],
  latestTurnStatus: ChatConversationController["latestTurnStatus"],
): string {
  switch (phase) {
    case "new": return "Ready for a new Chat";
    case "opening": return "Opening Turn";
    case "idle": return latestTurnStatus === "completed"
      ? "Run complete"
      : latestTurnStatus === "failed"
        ? "Run failed"
        : latestTurnStatus === "stopped" ? "Turn stopped" : "Ready";
    case "active": return "Research Agent is working";
    case "waiting_for_user": return "Waiting for your answer";
    case "stopping": return "Stopping Turn";
    case "recovering": return "Confirming command acceptance";
  }
}

function oneLine(value: string): string {
  return value.replace(/\s+/gu, " ").trim();
}
