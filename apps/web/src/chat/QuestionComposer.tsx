import { Sender } from "@ant-design/x";
import { Button, Card, Checkbox, Flex, Radio, Typography } from "antd";
import { X } from "@phosphor-icons/react";
import { useId } from "react";
import { useTranslation } from "react-i18next";
import type { ChatQuestion } from "./chatProtocol";
import type { ChatConversationController } from "./useChatConversation";

/** The product maps answer values; Ant Design owns choices, input and actions. */
export function QuestionComposer({ controller, question, locked, tooLarge }: {
  controller: ChatConversationController;
  question: ChatQuestion;
  locked: boolean;
  tooLarge: boolean;
}) {
  const { t } = useTranslation("chat");
  const optionId = useId();
  const multiple = question.selection_mode === "multi_select";
  const hasSelection = controller.answerSelections.length > 0;
  const choices = question.options?.map((option, index) => {
    const label = <Flex vertical gap={4}>
      <Typography.Text>{option.label}</Typography.Text>
      {option.description ? <Typography.Text type="secondary" id={`${optionId}-${index}`}>{option.description}</Typography.Text> : null}
    </Flex>;
    const props = { "aria-label": option.label,
      "aria-describedby": option.description ? `${optionId}-${index}` : undefined,
      value: option.label };
    return multiple ? <Checkbox {...props} key={option.label}>{label}</Checkbox>
      : <Radio {...props} key={option.label}>{label}</Radio>;
  });
  return <Card size="small" className="chat-question-composer" aria-labelledby="chat-question-title"
    style={{ display: "flex", flexDirection: "column", maxHeight: "min(560px, 65dvh)" }}
    styles={{ header: { flexShrink: 0, paddingBlock: 12 }, title: { whiteSpace: "normal" }, body: { display: "flex", flexDirection: "column", minHeight: 0, padding: 0, overflow: "hidden" } }}
    title={<Typography.Title level={5} id="chat-question-title" style={{ margin: 0 }}>{question.question}</Typography.Title>}
    extra={<Button aria-label={t("stop")} type="text" disabled={locked} icon={<X />} title={t("stopTurn")} onClick={() => void controller.stopTurn()} />}>
    <Flex vertical gap={12} className="chat-question-body" style={{ minHeight: 0, overflowY: "auto", padding: 16 }}>
      {choices ? <>
        <Flex align="center" justify="space-between" gap={12}>
          <Typography.Text type="secondary" id="chat-question-choice-help">{t(multiple ? "choiceMultiple" : "choiceSingle")}</Typography.Text>
          {hasSelection ? <Button type="text" size="small" disabled={locked} onClick={() => controller.setAnswerSelections([])}>{t("clear")}</Button> : null}
        </Flex>
        {multiple ? <Checkbox.Group aria-label={t("selectAll")} aria-describedby="chat-question-choice-help" disabled={locked}
          value={[...controller.answerSelections]} onChange={values => controller.setAnswerSelections(values.map(String))}>
          <Flex vertical gap={8}>{choices}</Flex>
        </Checkbox.Group> : <Radio.Group aria-label={t("selectOne")} aria-describedby="chat-question-choice-help" disabled={locked}
          value={controller.answerSelections[0] ?? ""} onChange={event => controller.setAnswerSelections([String(event.target.value)])}>
          <Flex vertical gap={8}>{choices}</Flex>
        </Radio.Group>}
      </> : null}
    </Flex>
    <Sender className="chat-question-answer-row" value={controller.draft} disabled={locked}
      style={{ flexShrink: 0 }} autoSize={{ minRows: 1, maxRows: 4 }}
      ref={instance => { controller.textareaRef.current = instance?.inputElement as HTMLTextAreaElement | null; }}
      aria-label={t("answerLabel")} aria-invalid={tooLarge || undefined}
      aria-describedby={tooLarge ? "chat-composer-guidance chat-composer-validation" : "chat-composer-guidance"}
      placeholder={t(hasSelection ? "answerNote" : "answerPlaceholder")} onChange={controller.setDraft}
      onSubmit={() => { if (!locked && !tooLarge && controller.action.kind === "answer" && controller.action.enabled) void controller.executeMainAction(); }}
      suffix={(_, { components: { SendButton } }) => <SendButton aria-label={t("answer")} disabled={locked || tooLarge || controller.action.kind !== "answer" || !controller.action.enabled} />} />
  </Card>;
}
