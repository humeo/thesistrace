import { changeInterfaceLanguage } from "../../src/i18n";

/** Fixture controls exercise the shared language owner without a second app shell. */
export function LanguageControls() {
  return <nav aria-label="Fixture language">
    <button type="button" onClick={() => changeInterfaceLanguage("en")}>English</button>
    <button type="button" onClick={() => changeInterfaceLanguage("zh-CN")}>简体中文</button>
  </nav>;
}
