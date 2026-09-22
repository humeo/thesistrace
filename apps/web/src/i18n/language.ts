export type InterfaceLocale = "en" | "zh-CN";
export const LANGUAGE_PREFERENCE_KEY = "quantgrove.interface-language";

export function initialInterfaceLocale(
  location: Readonly<{ pathname: string; search: string }>,
  storage: Pick<Storage, "getItem"> | null,
): InterfaceLocale {
  const query = new URLSearchParams(location.search);
  if (["/", "/login", "/accept-invitation"].includes(location.pathname) && !query.has("sig")) {
    const explicit = query.get("lang");
    if (explicit === "zh") return "zh-CN";
    if (explicit === "en") return "en";
  }
  try {
    if (storage?.getItem(LANGUAGE_PREFERENCE_KEY) === "zh-CN") return "zh-CN";
  } catch { /* Storage access is optional; English is the initial default. */ }
  return "en";
}

export function rememberInterfaceLocale(locale: InterfaceLocale, storage: Pick<Storage, "setItem"> | null): void {
  try { storage?.setItem(LANGUAGE_PREFERENCE_KEY, locale); }
  catch { /* The current page still changes language when persistence is unavailable. */ }
}

export function publicLanguageCode(locale: InterfaceLocale): "en" | "zh" {
  return locale === "zh-CN" ? "zh" : "en";
}

export function browserLanguageStorage(): Storage | null {
  try { return typeof window === "undefined" ? null : window.localStorage; }
  catch { return null; }
}
