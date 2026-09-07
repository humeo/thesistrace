import { CaretDown, Check } from "@phosphor-icons/react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import type { ResolvedModelSelection } from "./chatState";
import { reasoningEffortLabel, type AgentModelCatalog } from "./modelCatalog";

export function ModelPicker({
  catalog,
  onModelChange,
  onReasoningChange,
  selection,
}: {
  catalog: AgentModelCatalog;
  onModelChange: (modelKey: string) => void;
  onReasoningChange: (reasoningEffort: string) => void;
  selection: ResolvedModelSelection | null;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const selectedModel = rootRef.current?.querySelector<HTMLButtonElement>(
      '[data-picker-column="model"][aria-pressed="true"]',
    );
    const firstModel = rootRef.current?.querySelector<HTMLButtonElement>(
      '[data-picker-column="model"]',
    );
    window.requestAnimationFrame(() => (selectedModel ?? firstModel)?.focus());
    const dismiss = (event: PointerEvent) => {
      const target = event.target;
      if (target instanceof Node && !rootRef.current?.contains(target)) setOpen(false);
    };
    document.addEventListener("pointerdown", dismiss, true);
    return () => document.removeEventListener("pointerdown", dismiss, true);
  }, [open]);

  function closeAndRestore(): void {
    setOpen(false);
    window.requestAnimationFrame(() => triggerRef.current?.focus());
  }

  function handleMenuKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    if (event.key === "Escape") {
      event.preventDefault();
      closeAndRestore();
      return;
    }
    const target = event.target;
    if (!(target instanceof HTMLButtonElement)) return;
    const column = target.dataset.pickerColumn;
    if (column === undefined) return;
    const currentColumn = [...event.currentTarget.querySelectorAll<HTMLButtonElement>(
      `[data-picker-column="${column}"]`,
    )];
    const currentIndex = currentColumn.indexOf(target);
    if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      const nextIndex = event.key === "Home"
        ? 0
        : event.key === "End"
          ? currentColumn.length - 1
          : (currentIndex + (event.key === "ArrowDown" ? 1 : -1) + currentColumn.length) % currentColumn.length;
      currentColumn[nextIndex]?.focus();
      return;
    }
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    const nextColumn = column === "model" ? "reasoning" : "model";
    if ((event.key === "ArrowRight") !== (column === "model")) return;
    event.preventDefault();
    const selected = event.currentTarget.querySelector<HTMLButtonElement>(
      `[data-picker-column="${nextColumn}"][aria-pressed="true"]`,
    );
    const first = event.currentTarget.querySelector<HTMLButtonElement>(`[data-picker-column="${nextColumn}"]`);
    (selected ?? first)?.focus();
  }

  return (
    <div className={`chat-model-picker${open ? " chat-model-picker-open" : ""}`} ref={rootRef}>
      <button
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={selection === null
          ? "Choose model and reasoning for the next Turn"
          : `Model ${selection.model.display_name}, reasoning ${reasoningEffortLabel(selection.reasoningEffort)}`}
        className="chat-model-picker-trigger"
        onClick={() => setOpen((current) => !current)}
        onKeyDown={(event) => {
          if (!open && ["ArrowDown", "Enter", " "].includes(event.key)) {
            event.preventDefault();
            setOpen(true);
          }
        }}
        ref={triggerRef}
        type="button"
      >
        <strong>{selection?.model.display_name ?? "Choose model"}</strong>
        {selection === null ? null : <span>{reasoningEffortLabel(selection.reasoningEffort)}</span>}
        <CaretDown aria-hidden="true" size={14} />
      </button>
      {!open ? null : (
        <div
          aria-label="Model and reasoning for the next Turn"
          className="chat-model-picker-menu"
          onKeyDown={handleMenuKeyDown}
          role="dialog"
        >
          <div aria-label="Model" className="chat-model-picker-column" role="group">
            <span>Model</span>
            {catalog.models.map((model) => {
              const selected = selection?.model.key === model.key;
              return (
                <button
                  aria-pressed={selected}
                  data-picker-column="model"
                  key={model.key}
                  onClick={() => onModelChange(model.key)}
                  type="button"
                >
                  <span>{model.display_name}</span>
                  {selected ? <Check aria-hidden="true" size={13} weight="bold" /> : null}
                </button>
              );
            })}
          </div>
          <div aria-label="Reasoning" className="chat-model-picker-column" role="group">
            <span>Reasoning</span>
            {selection?.model.reasoning_efforts.map((effort) => {
              const selected = selection.reasoningEffort === effort;
              return (
                <button
                  aria-pressed={selected}
                  data-picker-column="reasoning"
                  key={effort}
                  onClick={() => {
                    onReasoningChange(effort);
                    closeAndRestore();
                  }}
                  type="button"
                >
                  <span>{reasoningEffortLabel(effort)}</span>
                  {selected ? <Check aria-hidden="true" size={13} weight="bold" /> : null}
                </button>
              );
            }) ?? <span className="chat-model-picker-empty">Choose a model</span>}
          </div>
        </div>
      )}
    </div>
  );
}
