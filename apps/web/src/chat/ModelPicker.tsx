import { CaretDown, Check } from "@phosphor-icons/react";
import { useRef, useState, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import "../i18n";
import { Button } from "../components/ui/button";
import { Popover, PopoverContent, PopoverTitle, PopoverTrigger } from "../components/ui/popover";
import { ToggleGroup, ToggleGroupItem } from "../components/ui/toggle-group";
import type { ResolvedModelSelection } from "./chatState";
import type { AgentModelCatalog, ReasoningEffort } from "./modelCatalog";

export function ModelPicker({ catalog, onModelChange, onReasoningChange, selection }: {
  catalog: AgentModelCatalog;
  onModelChange: (modelKey: string) => void;
  onReasoningChange: (reasoningEffort: string) => void;
  selection: ResolvedModelSelection | null;
}) {
  const { t } = useTranslation("chat");
  const effortLabel = (effort: ReasoningEffort) => t(`reasoningLabels.${effort}`);
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popupRef = useRef<HTMLDivElement>(null);
  const firstInColumn = (column: string) => popupRef.current?.querySelector<HTMLButtonElement>(`[data-picker-column="${column}"][aria-pressed="true"]`)
    ?? popupRef.current?.querySelector<HTMLButtonElement>(`[data-picker-column="${column}"]`) ?? null;

  // The two groups own vertical roving focus; Left/Right moves between settings.
  function moveColumn(event: KeyboardEvent<HTMLDivElement>) {
    const column = (event.target as HTMLElement).closest<HTMLElement>("[data-picker-column]")?.dataset.pickerColumn;
    if ((column === "model" && event.key === "ArrowRight") || (column === "reasoning" && event.key === "ArrowLeft")) {
      event.preventDefault();
      firstInColumn(column === "model" ? "reasoning" : "model")?.focus();
    }
  }
  return <Popover open={open} onOpenChange={setOpen}>
    <PopoverTrigger ref={triggerRef} render={<Button variant="ghost" className="min-w-0 max-w-full gap-2 px-2" />}
      aria-label={selection === null ? t("nextTurnModel") : t("selectedModel", { model: selection.model.display_name, reasoning: effortLabel(selection.reasoningEffort) })}
      onKeyDown={event => { if (!open && event.key === "ArrowDown") { event.preventDefault(); setOpen(true); } }}>
      <strong className="min-w-0 truncate text-sm">{selection?.model.display_name ?? t("chooseModel")}</strong>
      {selection ? <span className="text-xs">{effortLabel(selection.reasoningEffort)}</span> : null}<CaretDown aria-hidden="true" />
    </PopoverTrigger>
    <PopoverContent ref={popupRef} side="top" align="end" className="w-[min(380px,calc(100vw-32px))] gap-4 p-4" initialFocus={() => firstInColumn("model")} finalFocus={triggerRef} onKeyDown={moveColumn}>
      <PopoverTitle>{t("modelDialog")}</PopoverTitle>
      <div className="grid min-w-0 grid-cols-2 gap-4">
        <div className="min-w-0"><p className="m-0 mb-2 text-xs text-muted-foreground">{t("model")}</p>
          <ToggleGroup orientation="vertical" className="w-full" aria-label={t("model")} value={selection ? [selection.model.key] : []}
            onValueChange={values => { if (values[0]) onModelChange(values[0]); }}>
            {catalog.models.map(model => <ToggleGroupItem key={model.key} value={model.key} data-picker-column="model" className="h-auto min-h-11 w-full justify-between whitespace-normal text-left">
              <span className="min-w-0 [overflow-wrap:anywhere]">{model.display_name}</span>{selection?.model.key === model.key ? <Check aria-hidden="true" /> : null}
            </ToggleGroupItem>)}
          </ToggleGroup>
        </div>
        <div className="min-w-0 border-l border-border pl-4"><p className="m-0 mb-2 text-xs text-muted-foreground">{t("reasoning")}</p>
          {selection ? <ToggleGroup orientation="vertical" className="w-full" aria-label={t("reasoning")} value={[selection.reasoningEffort]}
            >
            {selection.model.reasoning_efforts.map(effort => <ToggleGroupItem key={effort} value={effort} onClick={() => { onReasoningChange(effort); setOpen(false); }} data-picker-column="reasoning" className="min-h-11 w-full justify-between">
              <span>{effortLabel(effort)}</span>{selection.reasoningEffort === effort ? <Check aria-hidden="true" /> : null}
            </ToggleGroupItem>)}
          </ToggleGroup> : <p className="text-xs text-muted-foreground">{t("chooseModel")}</p>}
        </div>
      </div>
    </PopoverContent>
  </Popover>;
}
