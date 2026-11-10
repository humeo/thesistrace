import { interfaceLocale, publicLanguageCode, useTranslation } from "../i18n";
import { publicPolicyPaths } from "./routes";

const titles = {
  en: ["Terms", "Privacy", "Refunds", "Pricing"],
  "zh-CN": ["服务条款", "隐私说明", "退款与取消", "套餐与额度"],
};
export function PolicyLinks({ includePricing = true }: { includePricing?: boolean }) {
  useTranslation();
  const locale = interfaceLocale();
  const label = includePricing ? (locale === "en" ? "Policies and pricing" : "政策与价格")
    : (locale === "en" ? "Policies" : "政策");
  return <nav aria-label={label} className="flex flex-wrap gap-4 text-sm">
    {publicPolicyPaths.map((path, index) => (includePricing || path !== "/pricing") && <a key={path} href={`${path}?lang=${publicLanguageCode(locale)}`} aria-current={window.location.pathname === path ? "page" : undefined}>{titles[locale][index]}</a>)}
  </nav>;
}
