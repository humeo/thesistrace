import { Question, X } from "@phosphor-icons/react";
import { useEffect, useId, useRef, useState, type MouseEvent } from "react";

export type MetricHelpContent = Readonly<{
  description: string;
  formula: string;
  range: string;
  direction: string;
  note?: string;
}>;

export function MetricHelp({ label, content }: { label: string; content: MetricHelpContent }) {
  const id = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const dismiss = (event: Event) => {
      if (event.target instanceof Node && panelRef.current?.contains(event.target)) return;
      panelRef.current?.hidePopover();
    };
    window.addEventListener("resize", dismiss);
    document.addEventListener("scroll", dismiss, true);
    return () => {
      window.removeEventListener("resize", dismiss);
      document.removeEventListener("scroll", dismiss, true);
    };
  }, [open]);

  function toggle(event: MouseEvent<HTMLButtonElement>) {
    event.preventDefault();
    const panel = panelRef.current;
    if (panel === null || !panel.togglePopover()) return;
    const trigger = event.currentTarget.getBoundingClientRect();
    const bounds = panel.getBoundingClientRect();
    const margin = 12;
    const gap = 8;
    panel.style.left = `${Math.max(margin, Math.min(
      trigger.right - bounds.width,
      document.documentElement.clientWidth - bounds.width - margin,
    ))}px`;
    panel.style.top = `${trigger.bottom + gap + bounds.height <= window.innerHeight - margin
      ? trigger.bottom + gap
      : Math.max(margin, trigger.top - bounds.height - gap)}px`;
  }

  return (
    <>
      <button
        aria-label={`About ${label}`}
        className="metric-help-trigger"
        onClick={toggle}
        popoverTarget={id}
        type="button"
      >
        <Question aria-hidden="true" size={15} />
      </button>
      <div
        aria-labelledby={`${id}-title`}
        className="metric-help-popover"
        id={id}
        lang="zh-CN"
        onToggle={(event) => setOpen(event.newState === "open")}
        popover="auto"
        ref={panelRef}
        role="dialog"
      >
        <header>
          <h3 id={`${id}-title`}>{label}</h3>
          <button aria-label="关闭说明" className="metric-help-close" popoverTarget={id} popoverTargetAction="hide" type="button">
            <X aria-hidden="true" size={15} />
          </button>
        </header>
        <p>{content.description}</p>
        <dl>
          <dt>计算口径</dt><dd>{content.formula}</dd>
          <dt>取值范围</dt><dd>{content.range}</dd>
          <dt>如何判断</dt><dd>{content.direction}</dd>
        </dl>
        {content.note === undefined ? null : <p className="metric-help-note">{content.note}</p>}
      </div>
    </>
  );
}
