import { XProvider } from "@ant-design/x";
import { App, theme } from "antd";
import enUS from "antd/locale/en_US";
import zhCN from "antd/locale/zh_CN";
import xEnUS from "@ant-design/x/locale/en_US";
import xZhCN from "@ant-design/x/locale/zh_CN";
import { useTranslation } from "react-i18next";
import type { ReactNode } from "react";

/** Scope the official Ant Design theme to the conversation, including its portals. */
export function ChatUiProvider({ children }: { children: ReactNode }) {
  const { i18n } = useTranslation();
  const chinese = i18n.resolvedLanguage === "zh-CN";
  return <XProvider locale={{ ...(chinese ? zhCN : enUS), ...(chinese ? xZhCN : xEnUS) }}
    theme={{ inherit: false, algorithm: theme.darkAlgorithm }}><App className="h-full min-h-0 min-w-0">{children}</App></XProvider>;
}
