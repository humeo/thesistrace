import { cn } from "cn";
import styles from "./ChatLayout.module.css";
import { ArrowUp, PencilSimple, X } from "@phosphor-icons/react";
import { useId, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { Checkbox } from "../components/ui/checkbox";
import { RadioGroup, RadioGroupItem } from "../components/ui/radio-group";
import { FieldLabel, FieldSet, FieldLegend, FieldGroup, Field } from "../components/ui/field";
import type { ChatQuestion } from "./chatProtocol";
import type { ChatConversationController } from "./useChatConversation";

export function QuestionComposer({ controller, question, locked, tooLarge, onKeyDown }: {
  controller: ChatConversationController;
  question: ChatQuestion;
  locked: boolean;
  tooLarge: boolean;
  onKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
}) {
  const { t } = useTranslation("chat");
  const optionId = useId();
  const multiple = question.selection_mode === "multi_select";
  const hasSelection = controller.answerSelections.length > 0;
  const choices = question.options?.map((option, index) => <FieldLabel key={option.label} className="chat-question-choice flex min-h-11 w-full items-start gap-3 rounded-md border border-border has-data-checked:border-primary has-data-checked:bg-muted">
    <Field orientation="horizontal" data-disabled={locked || undefined}>
    {multiple ? <Checkbox aria-labelledby={`${optionId}-${index}`} aria-describedby={option.description ? `${optionId}-${index}-description` : undefined} disabled={locked} checked={controller.answerSelections.includes(option.label)}
      onCheckedChange={checked => controller.setAnswerSelections(checked ? [...controller.answerSelections, option.label] : controller.answerSelections.filter(label => label !== option.label))} />
      : <RadioGroupItem aria-labelledby={`${optionId}-${index}`} aria-describedby={option.description ? `${optionId}-${index}-description` : undefined} disabled={locked} value={option.label} />}
    <span className="flex min-w-0 flex-col gap-1 [overflow-wrap:anywhere]"><strong id={`${optionId}-${index}`} className="text-sm font-medium">{option.label}</strong>{option.description ? <span id={`${optionId}-${index}-description`} className="text-xs font-normal text-muted-foreground">{option.description}</span> : null}</span>
    </Field>
  </FieldLabel>);
  return <section aria-labelledby="chat-question-title" className={cn("chat-question-composer flex min-h-0 flex-col overflow-hidden rounded-lg border border-border bg-card", styles.surface, styles.question)}>
    <div className="chat-question-body min-h-0 overflow-y-auto p-4">
      <header className="flex items-start justify-between gap-4"><h2 id="chat-question-title" className="m-0 text-base font-semibold [overflow-wrap:anywhere]">{question.question}</h2>
        <Button aria-label={t("stop")} variant="ghost" size="icon" disabled={locked} onClick={() => void controller.stopTurn()} title={t("stopTurn")} type="button"><X aria-hidden="true" /></Button>
      </header>
      {choices ? <>
        <div className="my-3 flex items-center justify-between gap-3 text-xs text-muted-foreground"><span id="chat-question-choice-help">{t(multiple ? "choiceMultiple" : "choiceSingle")}</span>{hasSelection ? <Button variant="ghost" disabled={locked} onClick={() => controller.setAnswerSelections([])} type="button">{t("clear")}</Button> : null}</div>
        <FieldSet disabled={locked} aria-describedby="chat-question-choice-help"><FieldLegend className="sr-only">{t(multiple ? "selectAll" : "selectOne")}</FieldLegend>
        {multiple ? <FieldGroup className="gap-2">{choices}</FieldGroup>
          : <RadioGroup aria-label={t("selectOne")} aria-describedby="chat-question-choice-help" value={controller.answerSelections[0] ?? ""} onValueChange={value => controller.setAnswerSelections([String(value)])}>{choices}</RadioGroup>}</FieldSet>
      </> : null}
    </div>
    <div className="chat-question-answer-row flex shrink-0 items-end gap-3 border-t border-border p-3">
      <PencilSimple aria-hidden="true" className="mb-3 shrink-0 text-muted-foreground" size={17} />
      <Textarea aria-label={t("answerLabel")} className={cn("min-h-11 min-w-0 flex-1 resize-none border-0 bg-transparent p-2 shadow-none focus-visible:ring-0", styles.questionInput)} aria-describedby={tooLarge ? "chat-composer-guidance chat-composer-validation" : "chat-composer-guidance"}
        aria-invalid={tooLarge || undefined} disabled={locked} onChange={event => controller.setDraft(event.target.value)} onKeyDown={onKeyDown}
        placeholder={t(hasSelection ? "answerNote" : "answerPlaceholder")} ref={controller.textareaRef} rows={1} value={controller.draft} />
      <Button aria-label={t("answer")} size="icon" type="submit" disabled={locked || controller.action.kind !== "answer" || !controller.action.enabled}><ArrowUp aria-hidden="true" weight="bold" /></Button>
    </div>
  </section>;
}
