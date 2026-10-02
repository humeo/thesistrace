import { useSyncExternalStore } from "react";
import { navigateCorePath } from "./navigation";

function subscribe(listener: () => void): () => void {
  window.addEventListener("popstate", listener);
  return () => window.removeEventListener("popstate", listener);
}

/** Keep page-level navigation in the address, independently of editable data. */
export function useUrlSelection<T extends string>(parameter: string, choices: readonly T[], initial: T) {
  const search = useSyncExternalStore(subscribe, () => window.location.search, () => "");
  const selected = choices.find(choice => choice === new URLSearchParams(search).get(parameter)) ?? initial;
  function select(value: string): void {
    if (!choices.some(choice => choice === value)) return;
    const url = new URL(window.location.href);
    if (url.searchParams.get(parameter) === value) return;
    url.searchParams.set(parameter, value);
    navigateCorePath(`${url.pathname}${url.search}${url.hash}`);
  }
  return [selected, select] as const;
}
