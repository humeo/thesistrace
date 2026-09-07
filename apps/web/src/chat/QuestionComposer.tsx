import { ArrowUp, Check, PencilSimple, X } from "@phosphor-icons/react";
import type { KeyboardEvent } from "react";

import type { ChatQuestion } from "./chatProtocol";
import type { ChatConversationController } from "./useChatConversation";

export function QuestionComposer({ controller, question, locked, tooLarge, onKeyDown }: {
  controller: ChatConversationController;
  question: ChatQuestion;
  locked: boolean;
  tooLarge: boolean;
  onKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
}) {
  const multiple = question.selection_mode === "multi_select";
  const hasSelection = controller.answerSelections.length > 0;
  return (
    <section aria-labelledby="chat-question-title" className="chat-composer-surface chat-question-composer">
      <div className="chat-question-body">
        <header className="chat-question-header">
          <h2 id="chat-question-title">{question.question}</h2>
          <button aria-label="Stop" className="chat-question-stop" disabled={locked}
            onClick={() => void controller.stopTurn()} title="Stop this Turn" type="button">
            <X aria-hidden="true" size={17} />
          </button>
        </header>
        {question.options === null ? null : (
          <>
            <div className="chat-question-choice-help">
              <span id="chat-question-choice-help">{multiple ? "Choose any that apply, or write your own" : "Choose one, or write your own"}</span>
              {hasSelection ? <button disabled={locked} onClick={() => controller.setAnswerSelections([])} type="button">Clear</button> : null}
            </div>
            <fieldset aria-describedby="chat-question-choice-help" className="chat-question-choices" disabled={locked}>
              <legend className="visually-hidden">{multiple ? "Select all that apply" : "Select one"}</legend>
              {question.options.map((option, index) => {
                const selected = controller.answerSelections.includes(option.label);
                return (
                  <label className={`chat-question-choice${selected ? " is-selected" : ""}`} key={option.label}>
                    <input aria-label={option.label} checked={selected} className="visually-hidden"
                      name={`question-${question.interrupt_id}`} type={multiple ? "checkbox" : "radio"}
                      onChange={() => controller.setAnswerSelections(multiple
                        ? selected ? controller.answerSelections.filter((label) => label !== option.label)
                          : [...controller.answerSelections, option.label]
                        : [option.label])} value={option.label} />
                    <span aria-hidden="true" className="chat-question-number">{selected ? <Check size={14} weight="bold" /> : index + 1}</span>
                    <span className="chat-question-option-text">
                      <strong>{option.label}</strong>
                      {option.description === undefined ? null : <small>{option.description}</small>}
                    </span>
                  </label>
                );
              })}
            </fieldset>
          </>
        )}
      </div>
      <div className="chat-question-answer-row">
        <PencilSimple aria-hidden="true" size={17} />
        <textarea aria-label="Answer" aria-describedby={tooLarge ? "chat-composer-guidance chat-composer-validation" : "chat-composer-guidance"}
          aria-invalid={tooLarge || undefined} disabled={locked}
          onChange={(event) => controller.setDraft(event.target.value)} onKeyDown={onKeyDown}
          placeholder={hasSelection ? "Add a note (optional)…" : "Write your own answer…"}
          ref={controller.textareaRef} rows={1} value={controller.draft} />
        <button aria-label="Send answer" className="chat-question-send" type="submit"
          disabled={locked || controller.action.kind !== "answer" || !controller.action.enabled}>
          <ArrowUp aria-hidden="true" size={17} weight="bold" />
        </button>
      </div>
    </section>
  );
}
