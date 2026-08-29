import type { MouseEvent } from "react";

export function navigateCorePath(path: string): void {
  const destination = new URL(path, window.location.href);
  window.history.pushState(
    null,
    "",
    `${destination.pathname}${destination.search}${destination.hash}`,
  );
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function followCoreLink(event: MouseEvent<HTMLAnchorElement>): void {
  const link = event.currentTarget;
  if (
    event.defaultPrevented
    || event.button !== 0
    || event.metaKey
    || event.ctrlKey
    || event.shiftKey
    || event.altKey
    || link.target === "_blank"
    || link.hasAttribute("download")
  ) return;

  const destination = new URL(link.href, window.location.href);
  if (destination.origin !== window.location.origin) return;

  event.preventDefault();
  navigateCorePath(`${destination.pathname}${destination.search}${destination.hash}`);
}
