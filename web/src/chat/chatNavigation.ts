import type { MouseEvent } from "react";

export function chatSessionHref(sessionId: string): string {
  return `/chat?${new URLSearchParams({ session: sessionId }).toString()}`;
}

export function handleChatNavigation(
  event: MouseEvent<HTMLAnchorElement>,
  navigate: () => void,
): void {
  if (
    event.button !== 0
    || event.metaKey
    || event.ctrlKey
    || event.shiftKey
    || event.altKey
  ) return;
  event.preventDefault();
  navigate();
}
