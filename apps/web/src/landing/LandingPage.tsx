import { PolicyLinks } from "../legal/PolicyLinks";
import { lazy, useEffect, useState } from 'react';
import { cn } from 'cn';
import { ArrowRightIcon, ArrowUpRightIcon, ChatCircleIcon, FlaskIcon, ChartLineIcon, FileTextIcon, PlugsIcon, CheckCircleIcon, GlobeIcon, MoonIcon, SunIcon, PauseIcon, PlayIcon } from '@phosphor-icons/react';
import { Brand } from '../brand/Brand';
import { Button, buttonVariants } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '../components/ui/tooltip';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { ToggleGroup, ToggleGroupItem } from '../components/ui/toggle-group';
import { Metric, MetricGroup } from '../components/product/MetricGroup';
import { changeInterfaceLanguage, interfaceLocale, publicLanguageCode, synchronizeEntryLanguage, useTranslation, type InterfaceLocale } from '../i18n';
import { DeferredPreview } from './DeferredPreview';
import { factorExamples, trackingExample } from './examples';
import './landing.css';

const sidebarIcons = [ChatCircleIcon, FileTextIcon, ChartLineIcon, FileTextIcon];
const capabilityIcons = [FlaskIcon, ChartLineIcon, ChartLineIcon, PlugsIcon];
const discordHref = 'https://discord.gg/tdwxubVhMJ';
const LandingConversationPreview = lazy(() => import('./LandingConversationPreview'));
const TrackingReturnChart = lazy(() => import('../daily-tracks/DailyTrackObservationView').then(module => ({ default: module.TrackingReturnChart })));

export default function Landing() {
  const { t: translate } = useTranslation('landing');
  const language = interfaceLocale();
  const t = translate('page', { returnObjects: true });
  const loginHref = `/login?lang=${publicLanguageCode(language)}`;
  const destination = (path: string) => `${loginHref}&returnTo=${encodeURIComponent(path)}`;
  const mcpHref = destination('/connections/mcp');
  const [appearance, setAppearance] = useState<'light' | 'dark'>('light');
  const [paused, setPaused] = useState(false);
  const [workspaceTab, setWorkspaceTab] = useState('chat');
  const [resultTab, setResultTab] = useState('evidence');
  const [factorIndex, setFactorIndex] = useState(0);
  const [horizon, setHorizon] = useState('5');
  const factor = factorExamples[factorIndex];
  const dark = appearance === 'dark';
  useEffect(() => {
    document.title = `${t.brand} — ${t.descriptor}`;
    document.querySelector('meta[name="description"]')?.setAttribute('content', t.meta);
  }, [language, t]);
  useEffect(() => {
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', dark ? '#131f1a' : '#f7f6f1');
    return () => { document.querySelector('meta[name="theme-color"]')?.setAttribute('content', '#010102'); };
  }, [dark]);
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
  const startLink = () => <a className={cn(buttonVariants({ size: 'xl' }), 'qh-start')} href={loginHref}>
    {t.start}<ArrowRightIcon aria-hidden="true" data-icon="inline-end" />
  </a>;
  const textLink = (href: string, label: string) => <a className="qh-text-link" href={href}>{label}<ArrowRightIcon size={18} aria-hidden="true" /></a>;
  const navLinks = <><a href="#preview">{t.product}</a><a href="#mcp">{t.mcp}</a><a href={discordHref} target="_blank" rel="noopener noreferrer">{t.community}<ArrowUpRightIcon size={14} aria-hidden="true" /></a></>;
  const comparison = <img className="qh-comparison" src={`/brand/rank-ic-${language === 'en' ? 'en' : 'zh'}.svg`} width={360} height={224} alt={t.comparisonDescription} />;
  const sidebarLinks = ['#preview', '#evidence', destination('/research'), destination('/research-runs')];
  const capabilityLinks = ['#preview', destination('/research'), '#tracking', '#mcp'];
  return <div className="landing-page" data-appearance={appearance} data-motion={paused ? 'paused' : 'running'}>
    <a className="qh-skip" href="#main">{t.skip}</a>
    <header className="qh-header">
      <div className="qh-header-inner qh-container">
        <a className="qh-brand" href="#top" aria-label={t.home}><Brand tone="jade" size={33} inverse={dark} /></a>
        <nav aria-label={t.navigation} className="qh-nav">{navLinks}</nav>
        <div className="qh-header-actions">
          <Button variant="ghost" size="icon-lg" aria-label={dark ? t.lightTheme : t.darkTheme} onClick={() => setAppearance(dark ? 'light' : 'dark')}>{dark ? <SunIcon /> : <MoonIcon />}</Button>
          <TooltipProvider><Tooltip>
            <TooltipTrigger render={<Button variant="ghost" size="lg" aria-label={t.languageToggle} onClick={() => changeLanguage(language === 'en' ? 'zh-CN' : 'en')} />}><GlobeIcon aria-hidden="true" data-icon="inline-start" /><span>{language === 'en' ? '中' : 'EN'}</span></TooltipTrigger>
            <TooltipContent side="bottom" role="tooltip">{language === 'en' ? 'English / 中文' : '中文 / English'}</TooltipContent>
          </Tooltip></TooltipProvider>
          <a className="qh-login" href={loginHref}>{t.login}</a>
        </div>
      </div>
    </header>
    <main id="main">
      <div className="qh-hero-stage" id="top">
        <section className="qh-hero qh-container" aria-labelledby="hero-title">
          <div className="qh-hero-cover" aria-hidden="true"><img src="/brand/editorial-cover.webp" width={1672} height={941} fetchPriority="high" alt="" /></div>
          <div className="qh-hero-copy">
            <h1 id="hero-title"><span>{t.headline[0]}</span><span>{t.headline[1]}</span></h1>
            <p className="qh-subtitle"><span>{t.descriptor}{language === 'en' ? '.' : '。'}</span><span>{t.subtitle}</span></p>
          </div>
          <div className="qh-margin-note" aria-hidden="true"><span>Ideas<br />Factors<br />Backtests<br />Evidence</span><p>{t.marginNote}</p></div>
        </section>
        <section id="preview" className="qh-product qh-container" aria-label={t.exampleResearch}>
          <div className="qh-app-frame">
            <div className="qh-workspace-heading"><a className="qh-brand" href="#top" aria-label={t.home}><Brand tone="jade" size={20} inverse={dark} /></a><span>{t.workspace}</span><Badge variant="outline">{t.historical}</Badge></div>
            <div className="qh-workspace-shell">
              <aside className="qh-example-sidebar" aria-label={t.product}>
                <ul>{t.workspaceNav.map((name, index) => { const Icon = sidebarIcons[index]; return <li key={name}><a href={sidebarLinks[index]} className={index === 0 ? 'qh-nav-selected' : undefined}><Icon size={20} aria-hidden="true" />{name}</a></li>; })}</ul>
                <div className="qh-sidebar-note"><span>Human + Agent</span><p>{t.workspaceNote}</p></div>
              </aside>
              <Tabs className="qh-workspace-main" value={workspaceTab} onValueChange={value => setWorkspaceTab(String(value))}>
                <TabsList variant="line" activateOnFocus aria-label={t.workspace}><TabsTrigger value="chat">{t.workspaceTabs[0]}</TabsTrigger><TabsTrigger value="results">{t.workspaceTabs[1]}</TabsTrigger></TabsList>
                <div className="qh-workspace-overview">
                  <div className="qh-workspace-body">
                    <TabsContent value="chat" keepMounted><div className="qh-example-conversation"><DeferredPreview height={350}><LandingConversationPreview appearance={appearance} onSelectFactor={setFactorIndex} /></DeferredPreview></div></TabsContent>
                    <TabsContent value="results"><h3>{t.comparisonTitle}</h3>{comparison}<p className="qh-small-note">{t.comparisonNote}</p></TabsContent>
                    {textLink('#evidence', t.inspectEvidence)}
                  </div>
                  <aside className="qh-inspector" aria-label={t.signal}><div className="qh-inspector-label">{t.researchEvidence}<FileTextIcon size={18} aria-hidden="true" /></div><h3>{t[factor.key]}</h3><p>{t.signal}</p><code>{factor.expression}</code><dl><div><dt>{t.inputLabels[2]}</dt><dd>close</dd></div><div><dt>{t.configLabels[1]}</dt><dd>{factorIndex === 0 ? '5' : '20'} {t.days}</dd></div></dl><p>{t.inspectorNote}</p>{textLink('#evidence', t.inspectEvidence)}</aside>
                </div>
              </Tabs>
            </div>
            <div className="qh-workspace-footer"><span><CheckCircleIcon aria-hidden="true" size={14} />{t.evaluationsCompleted}</span><span>{t.builtIn}</span></div>
          </div>
          <div className="qh-frame-caption"><span>{t.exampleNotice}</span><Button variant="ghost" size="sm" aria-label={paused ? t.resumeMotion : t.pauseMotion} aria-pressed={paused} onClick={() => setPaused(!paused)}>{paused ? <PlayIcon data-icon="inline-start" /> : <PauseIcon data-icon="inline-start" />}{paused ? t.resumeMotion : t.pauseMotion}</Button></div>
        </section>
      </div>
      <section id="evidence" className="qh-evidence-section qh-container" aria-labelledby="evidence-title">
        <div className="qh-section-copy"><h2 id="evidence-title">{t.evidenceTitle.join(' ')}</h2><p>{t.evidenceBody}</p></div>
        <nav className="qh-capabilities" aria-label={t.capabilities}>{t.capabilityNames.map((name, index) => { const Icon = capabilityIcons[index]; return <a href={capabilityLinks[index]} key={name}><Icon size={24} aria-hidden="true" /><div><h3>{name}</h3><p>{t.capabilityBodies[index]}</p></div></a>; })}</nav>
        <div className="qh-result-panel">
          <div className="qh-result-toolbar"><ToggleGroup value={[factor.key]} onValueChange={values => { if (values[0]) setFactorIndex(values[0] === 'reversal' ? 0 : 1); }} variant="outline" aria-label={t.selectFactor}>{factorExamples.map(item => <ToggleGroupItem key={item.key} value={item.key}>{t[item.key]}</ToggleGroupItem>)}</ToggleGroup><span>{t.exampleResearch}</span></div>
          <Tabs value={resultTab} onValueChange={value => setResultTab(String(value))}>
            <TabsList variant="line" activateOnFocus aria-label={t.exampleResult}>{['overview', 'evidence', 'inputs', 'configuration'].map((key, index) => <TabsTrigger key={key} value={key} size="lg">{t.resultTabs[index]}</TabsTrigger>)}</TabsList>
            <TabsContent value="overview"><MetricGroup label={t.resultTabs[0]} className="grid-cols-2 sm:grid-cols-2"><Metric label={t.rankOne} value={factor.oneDay} /><Metric label={t.rankFive} value={factor.fiveDay} /></MetricGroup><p className="qh-small-note">{t.evidenceNote}</p></TabsContent>
            <TabsContent value="evidence"><div className="qh-evidence-summary"><span className="qh-field-label">{t.selectedFactor}</span><h3>{t[factor.key]}</h3><code>{factor.expression}</code><ToggleGroup value={[horizon]} onValueChange={values => { if (values[0]) setHorizon(values[0]); }} variant="outline" aria-label={t.horizonLabel}>{['1', '5'].map((value, index) => <ToggleGroupItem key={value} value={value}>{t.horizons[index]}</ToggleGroupItem>)}</ToggleGroup><p className="qh-ic">Rank IC <strong>{horizon === '1' ? factor.oneDay : factor.fiveDay}</strong></p><p className="qh-small-note">{t.comparisonNote}</p></div><div className="qh-evidence-visual"><h3>{t.comparisonTitle}</h3>{comparison}{factorIndex === 0 ? <Table><TableHeader><TableRow><TableHead>{t.period}</TableHead><TableHead>{t.coverage}</TableHead></TableRow></TableHeader><TableBody><TableRow><TableCell>{t.august}</TableCell><TableCell>{horizon === '1' ? '19' : '15'} / 21 {t.days}</TableCell></TableRow></TableBody></Table> : <p className="qh-small-note">{t.contextUnavailable}</p>}</div></TabsContent>
            {(['inputs', 'configuration'] as const).map(key => <TabsContent key={key} value={key}><div className="qh-facts-heading"><h3>{t[factor.key]}</h3><code>{factor.expression}</code></div><dl className="qh-facts">{(key === 'inputs' ? t.inputLabels : t.configLabels).map((label, index) => <div key={label}><dt>{label}</dt><dd>{key === 'inputs' ? factorIndex === 1 && index < 2 ? t.contextUnavailable : t.inputValues[index] : index === 1 ? `${factorIndex === 0 ? '5' : '20'} ${t.days}` : t.configValues[index]}</dd></div>)}</dl></TabsContent>)}
          </Tabs>
          <div className="qh-evidence-bottom"><span>{t.evidenceFooter}</span>{textLink(destination('/research-runs'), t.openRuns)}</div>
        </div>
      </section>
      <section id="tracking" className="qh-tracking-band" aria-labelledby="tracking-title"><div className="qh-tracking qh-container">
        <div className="qh-section-copy"><h2 id="tracking-title">{t.trackingHeadline.map(line => <span key={line}>{line}</span>)}</h2><p>{t.dailyBody}</p><div className="qh-tracking-note"><span>{t.dailyTracking}</span><p>{t.trackingDetail}</p></div>{textLink(destination('/daily-tracks'), t.openTracking)}</div>
        <div className="qh-tracking-panel"><div className="qh-track-heading"><div><h3>{t.exampleStrategy}</h3><p>{t.dailyPeriod}</p></div><Badge variant="outline">{t.simulated}</Badge></div><MetricGroup variant="observation" label={t.dailyTracking} className="grid-cols-3">{['-1.23%', '8.30%', '13'].map((value, index) => <Metric key={value} variant="observation" label={t.metrics[index === 2 ? 3 : index]} value={value} />)}</MetricGroup><div className="qh-chart"><h3>{t.performance}</h3><DeferredPreview height={216}><TrackingReturnChart observation={trackingExample} originSession="2026-08-31" appearance={appearance} /></DeferredPreview></div><div className="qh-net-value"><span>{t.metrics[2]}</span><strong>¥1,424,714.10</strong></div><p className="qh-small-note">{t.dailyNote}</p></div>
      </div></section>
      <section id="mcp" className="qh-collaboration qh-container" aria-labelledby="mcp-title"><div className="qh-section-copy"><h2 id="mcp-title">{t.mcpTitle}</h2><p>{t.mcpBody}</p></div><div className="qh-collaboration-layout"><div className="qh-collaboration-art"><img src="/brand/editorial-cover.webp" width={1672} height={941} alt={t.coverAlt} loading="lazy" /></div><div className="qh-entry-options">{t.entryTitles.map((title, index) => <div className="qh-entry-option" key={title}><span className="qh-field-label">{t.entryLabels[index]}</span><h3>{title}</h3><p>{t.entryBodies[index]}</p>{textLink(index === 0 ? destination('/chat') : mcpHref, index === 0 ? t.openChat : t.connect)}</div>)}</div></div></section>
      <section className="qh-closing" aria-labelledby="closing-title"><img src="/brand/editorial-cover.webp" width={1672} height={941} alt="" loading="lazy" /><div className="qh-container"><h2 id="closing-title">{t.closing}</h2><p>{t.mcpBody}</p>{startLink()}</div></section>
    </main>
    <footer className="qh-footer qh-container"><div><a className="qh-brand" href="#top" aria-label={t.home}><Brand tone="jade" size={30} inverse={dark} /></a><p>{t.footerTagline}</p></div><div className="flex flex-col gap-4"><nav aria-label={t.footerNavigation}>{navLinks}</nav><PolicyLinks /></div></footer>
  </div>;
}
