import { Button, Checkbox, Divider, Flex, Popover, Radio, Slider, Typography } from "antd";
import { CaretDown } from "@phosphor-icons/react";
import { useRef, useState, type ComponentRef } from "react";
import { useTranslation } from "react-i18next";
import "../i18n";
import type { ResolvedModelSelection } from "./chatState";
import { supportedReasoningEfforts, type AgentModelCatalog, type ReasoningEffort } from "./modelCatalog";

export function ModelPicker({ catalog, onModelChange, onReasoningChange, onDefaultChange, selection }: {
  catalog: AgentModelCatalog;
  onModelChange: (modelKey: string) => void;
  onReasoningChange: (reasoningEffort: ReasoningEffort) => void;
  onDefaultChange: (followDefault: boolean) => void;
  selection: ResolvedModelSelection | null;
}) {
  const { t } = useTranslation("chat");
  const effortLabel = (effort: ReasoningEffort) => t(`reasoningLabels.${effort}`);
  const efforts = supportedReasoningEfforts.filter(effort => selection?.model.reasoning_efforts.includes(effort));
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<ComponentRef<typeof Button>>(null);
  return <Popover trigger="click" placement="topLeft" open={open} onOpenChange={setOpen} destroyOnHidden
    content={<div role="dialog" aria-label={t("modelDialog")} onKeyDown={event => {
      if (event.key === "Escape") { event.stopPropagation(); setOpen(false); triggerRef.current?.focus(); }
    }}><Flex vertical gap={8} style={{ width: 256 }}>
      <Typography.Text strong>{t("model")}</Typography.Text>
      <Checkbox checked={selection?.selectionMode === "default"} disabled={selection === null}
        onChange={event => onDefaultChange(event.target.checked)}>{t("followDefault")}</Checkbox>
      <Radio.Group aria-label={t("model")} orientation="vertical" value={selection?.model.key}
        onChange={event => onModelChange(String(event.target.value))}>
        {catalog.models.map((model, index) => <Radio value={model.key} key={model.key} aria-label={model.display_name}
          autoFocus={model.key === selection?.model.key || (selection === null && index === 0)}>{model.display_name}</Radio>)}
      </Radio.Group>
      <Divider style={{ marginBlock: 4 }} />
      <Flex align="center" justify="space-between"><Typography.Text strong>{t("reasoning")}</Typography.Text>
        {selection ? <Typography.Text type="secondary">{effortLabel(selection.reasoningEffort)}</Typography.Text> : null}
      </Flex>
      {selection && efforts.length > 1 ? <Slider min={0} max={efforts.length - 1} step={1} dots
        value={efforts.indexOf(selection.reasoningEffort)}
        marks={{ 0: effortLabel(efforts[0]), [efforts.length - 1]: effortLabel(efforts[efforts.length - 1]) }}
        ariaLabelForHandle={t("reasoning")} ariaValueTextFormatterForHandle={value => effortLabel(efforts[value])}
        tooltip={{ formatter: value => effortLabel(efforts[value!]) }} onChange={value => onReasoningChange(efforts[value])} />
        : selection === null ? <Typography.Text type="secondary">{t("chooseModel")}</Typography.Text> : null}
    </Flex></div>}>
    <Button ref={triggerRef} type="text" style={{ paddingInline: 4, gap: 4 }} aria-expanded={open} aria-haspopup="dialog"
      aria-label={selection === null ? t("nextTurnModel") : t("selectedModel", { model: selection.model.display_name, reasoning: effortLabel(selection.reasoningEffort) })}
      onKeyDown={event => { if (!open && event.key === "ArrowDown") { event.preventDefault(); setOpen(true); } }}>
      <Typography.Text type="secondary">{selection?.model.display_name ?? t("chooseModel")}{selection ? ` ${effortLabel(selection.reasoningEffort)}` : ""}</Typography.Text>
      <CaretDown aria-hidden="true" />
    </Button>
  </Popover>;
}
