import { useEffect } from "react";
import { Brand } from "../brand/Brand";
import { Button } from "../components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { changeInterfaceLanguage, interfaceLocale, publicLanguageCode, useTranslation } from "../i18n";
import { PolicyLinks } from "./PolicyLinks";
import { policyContent } from "./content";
import type { PublicPolicyPath } from "./routes";
import "./policy.css";

export default function PolicyPage({ path }: { path: PublicPolicyPath }) {
  useTranslation();
  const locale = interfaceLocale();
  const zh = locale === "zh-CN";
  const policy = policyContent[locale][path];
  useEffect(() => {
    document.title = `${policy.title} · QAgentis`;
    document.querySelector('meta[name="description"]')?.setAttribute("content", `${policy.title} — QAgentis`);
  }, [policy.title]);
  return <div className="policy-page">
    <a className="policy-skip" href="#policy-content">{zh ? "跳到正文" : "Skip to content"}</a>
    <header className="policy-header">
      <a href={`/?lang=${publicLanguageCode(locale)}`} aria-label={zh ? "QAgentis 首页" : "QAgentis home"}><Brand size={30} inverse /></a>
      <Button variant="outline" onClick={() => {
        const next = zh ? "en" : "zh-CN";
        changeInterfaceLanguage(next);
        const url = new URL(window.location.href);
        url.searchParams.set("lang", publicLanguageCode(next));
        window.history.replaceState(null, "", url);
      }}>{zh ? "English" : "中文"}</Button>
    </header>
    <PolicyLinks />
    <main id="policy-content">
      <h1>{policy.title}</h1>
      <p className="policy-notice">{zh
        ? "上线前预览 · 正式运营主体及完整隐私信息将在开放付费订阅前公布。本页尚非最终生效版本。"
        : "Pre-launch preview · Operator details and the complete privacy notice will be published before paid subscriptions open. This is not the final effective version."}</p>
      {path === "/pricing" && <Table>
        <TableHeader><TableRow>{(zh ? ["套餐", "USD / 月", "研究 / 日", "跟踪名额", "AI 用量"] : ["Plan", "USD / month", "Runs / day", "Tracking slots", "AI usage"]).map(label => <TableHead key={label}>{label}</TableHead>)}</TableRow></TableHeader>
        <TableBody>{[["Free", "$0", "10", "1", "$1"], ["Pro", "$20", "100", "10", "$1.5"], ["Max", "$100", "500", "50", "$2"]].map((row, planIndex) => <TableRow key={row[0]}>{row.map((cell, index) => <TableCell key={index}>{index === 4
          ? <div className="flex flex-col gap-1"><span>{(zh ? ["基础用量", "更多用量", "充裕用量"] : ["Basic usage", "More usage", "Generous usage"])[planIndex]}</span><span className="text-xs text-muted-foreground">{zh ? `约 ${cell}／天` : `About ${cell} / day`}</span></div>
          : cell}</TableCell>)}</TableRow>)}</TableBody>
      </Table>}
      {policy.sections.map(section => <section key={section.title}>
        <h2>{section.title}</h2>
        {section.paragraphs.map(paragraph => <p key={paragraph}>{paragraph}</p>)}
      </section>)}
      {path === "/privacy" && <p><a href="https://www.creem.io/privacy">{zh ? "Creem 隐私政策" : "Creem privacy notice"}</a></p>}
    </main>
    <footer><PolicyLinks /><p>{zh ? "支持与隐私联系：" : "Support and privacy: "}<a href="mailto:koltenluca433@gmail.com">koltenluca433@gmail.com</a></p></footer>
  </div>;
}
