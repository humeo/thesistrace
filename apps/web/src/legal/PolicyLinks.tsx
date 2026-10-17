import { interfaceLocale, publicLanguageCode, useTranslation } from "../i18n";
import { publicPolicyPaths } from "./routes";

const titles = {
  en: ["Terms", "Privacy", "Refunds", "Pricing"],
  "zh-CN": ["服务条款", "隐私说明", "退款与取消", "套餐与额度"],
};
export function PolicyLinks() {
  useTranslation();
  const locale = interfaceLocale();
  return <nav aria-label={locale === "en" ? "Policies and pricing" : "政策与价格"} className="flex flex-wrap gap-4 text-sm">
    {publicPolicyPaths.map((path, index) => <a key={path} href={`${path}?lang=${publicLanguageCode(locale)}`} aria-current={window.location.pathname === path ? "page" : undefined}>{titles[locale][index]}</a>)}
  </nav>;
}
