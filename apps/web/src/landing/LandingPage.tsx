import { useEffect, useState } from 'react';
import { cn } from 'cn';
import { ArrowRightIcon, ChatCircleIcon, DatabaseIcon, FlaskIcon, ChartLineIcon, ListChecksIcon, PlugsIcon, CheckCircleIcon } from '@phosphor-icons/react';
import { Bubble, Sender } from '@ant-design/x';
import { Brand, BrandMark } from '../brand/Brand';
import { ChatUiProvider } from '../chat/ChatUiProvider';
import { Button, buttonVariants } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '../components/ui/tooltip';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { ToggleGroup, ToggleGroupItem } from '../components/ui/toggle-group';
import { Metric, MetricGroup } from '../components/product/MetricGroup';
import { TrackingReturnChart } from '../daily-tracks/DailyTrackObservationView';
import { changeInterfaceLanguage, interfaceLocale, publicLanguageCode, synchronizeEntryLanguage, useTranslation, type InterfaceLocale } from '../i18n';
import { LanguageIcon } from './LanguageIcon';
import { factorExamples, trackingExample } from './examples';
import './landing.css';

const sidebarIcons = [ChatCircleIcon, DatabaseIcon, FlaskIcon, ListChecksIcon, ChartLineIcon, PlugsIcon];
const sidebarRoutes = ['/chat', '/data', '/research', '/research-runs', '/daily-tracks', '/connections/mcp'];
const discordHref = 'https://discord.gg/tdwxubVhMJ';

export default function Landing() {
  const { t: translate } = useTranslation('landing');
  const language = interfaceLocale();
  const t = translate('page', { returnObjects: true });
  const loginHref = `/login?lang=${publicLanguageCode(language)}`;
  const mcpHref = `${loginHref}&returnTo=${encodeURIComponent('/connections/mcp')}`;
  const [resultTab, setResultTab] = useState('evidence');
  const [horizon, setHorizon] = useState('5');
  useEffect(() => {
    document.title = `${t.brand} — ${t.descriptor}`;
    document.querySelector('meta[name="description"]')?.setAttribute('content', t.meta);
  }, [language, t]);
  useEffect(() => {
    window.addEventListener('popstate', synchronizeEntryLanguage);
    return () => window.removeEventListener('popstate', synchronizeEntryLanguage);
  }, []);
  const changeLanguage = (next: InterfaceLocale) => {
    const url = new URL(location.href);
    url.searchParams.set('lang', publicLanguageCode(next));
    history.replaceState(null, '', url);
    changeInterfaceLanguage(next);
  };
  const startLink = (large = false) => <a className={cn(buttonVariants({ size: large ? 'xl' : 'lg' }))} href={loginHref}>
    {t.start}<ArrowRightIcon aria-hidden="true" data-icon="inline-end" />
  </a>;
  const navLinks = <><a href="#preview">{t.product}</a><a href={mcpHref}>{t.mcp}</a><a href={discordHref} target="_blank" rel="noopener noreferrer">{t.community}</a></>;
  return <div className="landing-page">
    <a className="qh-skip" href="#top">{t.product}</a>
    <header className="qh-header qh-container">
      <a className="qh-brand" href="#top" aria-label={t.home}><Brand size={24} inverse /></a>
      <nav aria-label={t.navigation} className="qh-nav">{navLinks}</nav>
      <div className="qh-header-actions">
        <TooltipProvider><Tooltip>
          <TooltipTrigger render={<Button variant="ghost" size="icon-xl" aria-label={t.languageToggle} onClick={() => changeLanguage(language === 'en' ? 'zh-CN' : 'en')} />}><LanguageIcon language={language} /></TooltipTrigger>
          <TooltipContent side="bottom" role="tooltip">{language === 'en' ? 'English / 中文' : '中文 / English'}</TooltipContent>
        </Tooltip></TooltipProvider>
        <a className="qh-login" href={loginHref}>{t.login}</a>{startLink()}
      </div>
    </header>
    <main id="top">
      <section className="qh-hero qh-container" aria-labelledby="hero-title">
        <h1 id="hero-title">{t.headline[0]}<br />{t.headline[1]}</h1>
        <p className="qh-subtitle">{t.subtitle}</p>
        <div className="qh-hero-actions">{startLink(true)}<a className="qh-example-link" href="#preview">{t.viewExample}<ArrowRightIcon aria-hidden="true" size={16} /></a></div>
      </section>
      <section id="preview" className="qh-product qh-container" aria-label={t.exampleResearch}>
        <div className="qh-app-frame">
          <aside className="qh-example-sidebar" aria-label={t.product}>
            <a className="qh-brand" href="#top" aria-label={t.home}><Brand size={20} inverse /></a>
            <ul>{t.sidebar.map((name, index) => {
              const Icon = sidebarIcons[index];
              return <li key={index}><a href={`${loginHref}&returnTo=${encodeURIComponent(sidebarRoutes[index])}`} className={index === 0 ? 'qh-nav-selected' : undefined}><Icon size={18} aria-hidden="true" />{name}</a></li>;
            })}</ul>
          </aside>
          <div className="qh-example-conversation"><ChatUiProvider>
            <Bubble.List autoScroll={false} items={[
              { key: 'question', role: 'user', placement: 'end', variant: 'filled', content: t.question },
              { key: 'answer', role: 'ai', variant: 'borderless', avatar: <BrandMark size={24} inverse />, content: <>
                <p>{t.answer}</p>
                <Table className="qh-research-table"><TableHeader><TableRow><TableHead>{t.researchName}</TableHead><TableHead>{t.rankOne}</TableHead><TableHead>{t.rankFive}</TableHead></TableRow></TableHeader>
                  <TableBody>{factorExamples.map(item => <TableRow key={item.key}>
                    <TableCell>{item.key === 'reversal' ? <a href="#evidence">{t[item.key]}</a> : <span className="qh-research-name">{t[item.key]}</span>}<Badge variant="outline"><CheckCircleIcon aria-hidden="true" />{t.completed}</Badge><code>{item.expression}</code></TableCell><TableCell>{item.oneDay}</TableCell><TableCell>{item.fiveDay}</TableCell>
                  </TableRow>)}</TableBody>
                </Table>
              </> },
            ]} />
            <Sender disabled placeholder={t.ask} aria-label={t.ask} footer={<span>{t.builtIn}</span>} />
          </ChatUiProvider></div>
        </div>
        <div className="qh-frame-caption"><span>{t.exampleResearch}</span><a href={mcpHref}>{t.connect}<ArrowRightIcon size={16} aria-hidden="true" /></a></div>
        <p className="qh-example-notice">{t.exampleNotice}</p>
      </section>
      <section id="evidence" className="qh-evidence-section qh-container" aria-labelledby="evidence-title">
        <div className="qh-section-copy" id="method"><h2 id="evidence-title">{t.evidenceTitle[0]}<br />{t.evidenceTitle[1]}</h2><p>{t.evidenceBody}</p></div>
        <div className="qh-result-example">
          <div className="qh-result-panel">
            <p className="qh-breadcrumb">{t.sidebar[3]} / {t.reversal}</p>
            <div className="qh-result-heading"><h3>{t.reversal}</h3><Badge variant="secondary">{t.factor}</Badge><Badge variant="outline"><CheckCircleIcon aria-hidden="true" />{t.completed}</Badge></div>
            <Tabs value={resultTab} onValueChange={value => setResultTab(String(value))}>
              <TabsList variant="line" activateOnFocus aria-label={t.exampleResult}>{['overview', 'evidence', 'inputs', 'configuration'].map((key, index) => <TabsTrigger key={key} value={key} size="lg">{t.resultTabs[index]}</TabsTrigger>)}</TabsList>
              <TabsContent value="overview"><MetricGroup label={t.resultTabs[0]} className="grid-cols-2 sm:grid-cols-2"><Metric label={t.rankOne} value="0.082" /><Metric label={t.rankFive} value="0.043" /></MetricGroup><p className="qh-evidence-note">{t.evidenceNote}</p></TabsContent>
              <TabsContent value="evidence">
                <code className="qh-formula">{factorExamples[0].expression}</code>
                <ToggleGroup value={[horizon]} onValueChange={values => { if (values[0]) setHorizon(values[0]); }} variant="outline" aria-label={t.horizonLabel}>{['1', '5'].map((value, index) => <ToggleGroupItem key={value} value={value}>{t.horizons[index]}</ToggleGroupItem>)}</ToggleGroup>
                <Table><TableHeader><TableRow><TableHead>{t.period}</TableHead><TableHead>Rank IC</TableHead><TableHead>{t.coverage}</TableHead></TableRow></TableHeader><TableBody><TableRow><TableCell>{t.august}</TableCell><TableCell>{horizon === '1' ? '0.082' : '0.043'}</TableCell><TableCell>{horizon === '1' ? '19' : '15'} / 21 {t.days}</TableCell></TableRow></TableBody></Table>
              </TabsContent>
              {(['inputs', 'configuration'] as const).map(key => <TabsContent key={key} value={key}><dl className="qh-facts">{(key === 'inputs' ? t.inputLabels : t.configLabels).map((label, index) => <div key={index}><dt>{label}</dt><dd>{(key === 'inputs' ? t.inputValues : t.configValues)[index]}</dd></div>)}</dl></TabsContent>)}
            </Tabs>
          </div>
          <p className="qh-frame-caption">{t.exampleResult}</p>
        </div>
      </section>
      <section id="tracking" className="qh-tracking qh-container" aria-labelledby="tracking-title">
        <div className="qh-section-copy"><h2 id="tracking-title">{t.dailyTitle}</h2><p>{t.dailyBody}</p></div>
        <div className="qh-tracking-panel">
          <div className="qh-track-heading"><div><h3>{t.dailyTracking}</h3><p>{t.exampleStrategy}</p></div><span>{t.dailyPeriod}</span></div>
          <MetricGroup variant="observation" label={t.dailyTracking} className="grid-cols-4">{['-1.23%', '8.30%', '¥1,424,714.10', '13'].map((value, index) => <Metric key={index} variant="observation" label={t.metrics[index]} value={value} />)}</MetricGroup>
          <div className="qh-chart"><h3>{t.performance}</h3><TrackingReturnChart observation={trackingExample} originSession="2026-08-31" /></div>
          <p className="qh-daily-note">{t.dailyNote}</p>
        </div>
        <p className="qh-frame-caption">{t.exampleTrack}</p>
      </section>
      <section className="qh-closing qh-container" aria-labelledby="closing-title"><h2 id="closing-title">{t.closing}</h2>{startLink(true)}</section>
    </main>
    <footer className="qh-footer qh-container"><a className="qh-brand" href="#top" aria-label={t.home}><Brand size={20} inverse /></a><nav aria-label={t.navigation}>{navLinks}</nav><span>© {new Date().getFullYear()} QAgentis</span></footer>
  </div>;
}
