import React, { useEffect, useRef, useState } from 'react';
import { Brand } from '../brand/Brand';
import { copy, type Language } from './copy';
import './landing.css';
export default function Landing() {
    const [language, setLanguage] = useState<Language>(() => new URLSearchParams(location.search).get('lang') === 'zh' ? 'zh' : 'en');
    const t = copy[language];
    const [stage, setStage] = useState(0);
    const previewRef = useRef<HTMLElement>(null);
    useEffect(() => {
        document.documentElement.lang = language === 'zh' ? 'zh-CN' : 'en';
        document.title = `${t.brand} — ${t.descriptor}`;
        document.querySelector('meta[name="description"]')?.setAttribute('content', t.meta);
    }, [language, t]);
    useEffect(() => {
        const synchronize = () => setLanguage(new URLSearchParams(location.search).get('lang') === 'zh' ? 'zh' : 'en');
        window.addEventListener('popstate', synchronize);
        return () => window.removeEventListener('popstate', synchronize);
    }, []);
    const changeLanguage = (next: Language) => {
        const url = new URL(location.href);
        url.searchParams.set('lang', next);
        history.replaceState(null, '', url);
        setLanguage(next);
    };
    const selectStage = (index: number) => {
        setStage(index);
        previewRef.current?.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start' });
    };
    return <div className="landing-page">
    <header className="qt-header">
      <a className="qt-brand" href="#top" aria-label={t.home}><Brand className="qt-logo" size={32} /></a>
      <nav aria-label={t.navigation}>
        <a className="qt-community" href="https://discord.gg/tdwxubVhMJ" target="_blank" rel="noopener noreferrer" aria-label={t.community} title={t.community}><img src="/brand/discord-symbol-white.svg" alt="" width={20} height={15}/><span>Discord</span></a>
        <div className="qt-language" role="group" aria-label="Language / 语言">
          <button type="button" lang="en" aria-label="English" aria-pressed={language === 'en'} onClick={() => changeLanguage('en')}>EN</button>
          <span aria-hidden="true">/</span>
          <button type="button" lang="zh-CN" aria-pressed={language === 'zh'} onClick={() => changeLanguage('zh')}>中文</button>
        </div>
        <a className="qt-login" href="/login">{t.login}<span aria-hidden="true">↗</span></a>
      </nav>
    </header>
    <main id="top">
      <section className="qt-hero" aria-labelledby="hero-title">
        <div className="qt-hero-copy">
          <h1 id="hero-title">{t.headline[0]}<span className="qt-headline-ending">{t.headline[1]}</span></h1>
          <p className="qt-descriptor">{t.descriptor}</p>
          <p className="qt-subtitle">{t.subtitle}</p>
          <div className="qt-hero-actions"><a className="qt-primary" href="/login">{t.start}</a><a className="qt-secondary" href="#preview">{t.viewExample}</a></div>
        </div>
        <img className="qt-hero-image" src="/brand/quantgrove-botanical.jpg" alt="" width={570} height={760} fetchPriority="high" />
      </section>
      <section id="method" className="qt-method" aria-label={t.stepsLabel}>
        {t.stages.map((item, index) => <button className="qt-stage" key={index} onClick={() => selectStage(index)} aria-label={`${item.title}: ${t.viewExample}`}><span className="qt-number">0{index + 1}</span><h2>{item.title}</h2><p>{item.description}</p></button>)}
      </section>
      <section id="preview" ref={previewRef} className="qt-preview" aria-labelledby="preview-title">
        <div className="qt-preview-intro"><div><span className="qt-caption">{t.preview}</span><h2 id="preview-title">{t.previewTitle}</h2></div><p>{t.previewIntro}<br />{t.previewNote}</p></div>
        <div className="qt-tabs" role="tablist" aria-label={t.stagesLabel}>
          {t.stages.map((item, index) => <button id={`stage-${index}`} role="tab" aria-selected={stage === index} aria-controls="stage-panel" tabIndex={stage === index ? 0 : -1} onKeyDown={event => { if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
        event.preventDefault();
        const next = (stage + (event.key === 'ArrowRight' ? 1 : 2)) % 3;
        setStage(next);
        document.getElementById(`stage-${next}`)?.focus();
    } }} onClick={() => setStage(index)} key={index}>{item.title}</button>)}
        </div>
        <div id="stage-panel" role="tabpanel" aria-labelledby={`stage-${stage}`} className="qt-preview-body">
          <div aria-live="polite"><span className="qt-caption">{t.stages[stage].label}</span><h3>{t.stages[stage].detail}</h3><p>{t.stages[stage].body}</p>
            {stage === 0 ? <div className="qt-formula"><span>{t.alpha}</span><code>-rank(ts_delta(close, 5))</code></div> : <dl>{(stage === 1 ? t.validation : t.tracking).map(([term, description]) => <div key={term}><dt>{term}</dt><dd>{description}</dd></div>)}</dl>}
          </div>
          <button className="qt-next" onClick={() => setStage((stage + 1) % 3)}>{t.stages[stage].action}</button>
        </div>
      </section>
      <section className="qt-value" aria-labelledby="value-title">
        <h2 id="value-title">{t.valueTitle}</h2>
        <div className="qt-value-reasons">{t.reasons.map(([title, body]) => <article key={title}><h3>{title}</h3><p>{body}</p></article>)}</div>
      </section>
      <section className="qt-access"><h2>{t.accessTitle}</h2><p>{t.accessBody}</p><a className="qt-primary" href="/login">{t.login}</a></section>
    </main>
    <footer><a className="qt-brand" href="#top" aria-label={t.home}><Brand className="qt-logo" size={24} /></a><p>{t.footer}</p><a className="qt-footer-community" href="https://discord.gg/tdwxubVhMJ" target="_blank" rel="noopener noreferrer">{t.community}</a></footer>
  </div>;
}
