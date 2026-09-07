import type { KeyboardEvent } from "react";

export function containDialogKeyboardFocus(
  event: KeyboardEvent<HTMLDialogElement>,
  element: HTMLDialogElement | null,
): void {
  if (event.key !== "Tab" || element === null) return;
  const targets = Array.from(
    element.querySelectorAll<HTMLElement>(
      "input:not(:disabled), button:not(:disabled)",
    ),
  );
  const first = targets[0];
  const last = targets.at(-1);
  if (first === undefined || last === undefined) {
    event.preventDefault();
    return;
  }
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
    return;
  }
  if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}
