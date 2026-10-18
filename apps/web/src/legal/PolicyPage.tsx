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
      <p className="policy-notice">{zh ? "生效日期：2026 年 10 月 18 日" : "Effective date: October 18, 2026"}</p>
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
      {path === "/privacy" && <section>
        <h2>{zh ? "相关服务商说明" : "Provider information"}</h2>
        <ul>
          <li><a href="https://www.creem.io/privacy">{zh ? "Creem 隐私政策" : "Creem privacy notice"}</a></li>
          <li><a href="https://openai.com/policies/privacy-policy/">{zh ? "OpenAI 隐私政策" : "OpenAI privacy policy"}</a> · <a href="https://openai.com/business-data/">{zh ? "OpenAI 业务数据说明" : "OpenAI business data information"}</a></li>
          <li><a href="https://resend.com/legal/privacy-policy">{zh ? "Resend 隐私政策" : "Resend privacy policy"}</a></li>
          <li><a href="https://www.cloudflare.com/privacypolicy/">{zh ? "Cloudflare 隐私政策" : "Cloudflare privacy policy"}</a></li>
          <li><a href="https://policies.google.com/privacy">{zh ? "Google 隐私政策" : "Google privacy policy"}</a></li>
        </ul>
      </section>}
      {(path === "/terms" || path === "/refunds") && <p><a href="https://www.creem.io/buyer-terms">{zh ? "Creem 购买条款" : "Creem Buyer Terms"}</a></p>}
    </main>
    <footer><PolicyLinks /><p>{zh ? "支持与隐私联系：" : "Support and privacy: "}<a href="mailto:koltenluca433@gmail.com">koltenluca433@gmail.com</a></p></footer>
  </div>;
}
