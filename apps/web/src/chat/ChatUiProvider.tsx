import { XProvider } from "@ant-design/x";
import { App, theme } from "antd";
import enUS from "antd/locale/en_US";
import zhCN from "antd/locale/zh_CN";
import xEnUS from "@ant-design/x/locale/en_US";
import xZhCN from "@ant-design/x/locale/zh_CN";
import { useTranslation } from "react-i18next";
import type { ReactNode } from "react";

const CHINESE_LOCALE = { ...zhCN, ...xZhCN };
const ENGLISH_LOCALE = { ...enUS, ...xEnUS };
const CHAT_THEMES = { dark: { inherit: false, algorithm: theme.darkAlgorithm }, light: { inherit: false, algorithm: theme.defaultAlgorithm } };

/** Scope the official Ant Design theme to the conversation, including its portals. */
export function ChatUiProvider({ children, appearance = "dark" }: { children: ReactNode; appearance?: "dark" | "light" }) {
  const { i18n } = useTranslation();
  const chinese = i18n.resolvedLanguage === "zh-CN";
  return <XProvider locale={chinese ? CHINESE_LOCALE : ENGLISH_LOCALE}
    theme={CHAT_THEMES[appearance]}><App className="h-full min-h-0 min-w-0">{children}</App></XProvider>;
}
