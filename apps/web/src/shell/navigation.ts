import type { MouseEvent } from "react";

export type WorkspaceNavigate = (href: string, options?: Readonly<{ replace?: boolean }>) => void;

export function handleWorkspaceNavigation(event: MouseEvent<HTMLAnchorElement>, navigate: () => void): void {
  if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey
    || event.shiftKey || event.altKey || event.currentTarget.hasAttribute("download")
    || (event.currentTarget.target !== "" && event.currentTarget.target !== "_self")) return;
  event.preventDefault();
  navigate();
}

export function navigateCorePath(path: string): void {
  const destination = new URL(path, window.location.href);
  window.history.pushState(null, "", `${destination.pathname}${destination.search}${destination.hash}`);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function followCoreLink(event: MouseEvent<HTMLAnchorElement>): void {
  const destination = new URL(event.currentTarget.href, window.location.href);
  if (destination.origin !== window.location.origin) return;
  handleWorkspaceNavigation(event, () => {
    navigateCorePath(`${destination.pathname}${destination.search}${destination.hash}`);
  });
}
