import { createInstance } from "i18next";
import { initReactI18next } from "react-i18next";
import { resources } from "./resources";
import { browserLanguageStorage, initialInterfaceLocale, rememberInterfaceLocale, type InterfaceLocale } from "./language";

export { useTranslation } from "react-i18next";
export { publicLanguageCode, type InterfaceLocale } from "./language";

export const i18n = createInstance();
void i18n.use(initReactI18next).init({
  resources,
  lng: typeof window === "undefined" ? "en" : initialInterfaceLocale(window.location, browserLanguageStorage()),
  supportedLngs: ["en", "zh-CN"],
  fallbackLng: false,
  load: "currentOnly",
  defaultNS: "common",
  ns: Object.keys(resources.en),
  initAsync: false,
  interpolation: { escapeValue: false },
  react: { useSuspense: false },
});

function synchronizeDocumentLanguage(): void {
  if (typeof document !== "undefined") document.documentElement.lang = interfaceLocale();
}
i18n.on("languageChanged", synchronizeDocumentLanguage);
synchronizeDocumentLanguage();

export function interfaceLocale(): InterfaceLocale {
  return i18n.language === "zh-CN" ? "zh-CN" : "en";
}

export function changeInterfaceLanguage(locale: InterfaceLocale): void {
  rememberInterfaceLocale(locale, browserLanguageStorage());
  void i18n.changeLanguage(locale);
}

/** Public history navigation may override this entry's language without saving a choice. */
export function synchronizeEntryLanguage(): void {
  void i18n.changeLanguage(initialInterfaceLocale(window.location, browserLanguageStorage()));
}
