import { randomUUID } from "node:crypto";
import type { Page } from "@playwright/test";

/** Replay the official SDK boundary; deterministic browser tests never call Cloudflare. */
export async function serveTurnstile(page: Page) {
  await page.route("https://challenges.cloudflare.com/turnstile/v0/api.js**", async route => route.fulfill({contentType:"application/javascript", body: `
    const widgets = new Map();
    const seed = ${JSON.stringify(randomUUID())};
    let sequence = 0;
    const uuid = () => seed.slice(0,24) + (++sequence).toString(16).padStart(12,"0");
    function issue(id) { const item=widgets.get(id); if(!item)return; const token='test-turnstile:'+location.hostname+':'+Date.now()+':'+uuid(); item.token=token; queueMicrotask(()=>item.options.callback(token)); }
    window.turnstile = {
      render(element, options) {const id=uuid();widgets.set(id,{element,options});element.textContent='Browser verified';issue(id);return id;},
      reset(id) {issue(id);},
      remove(id) {const item=widgets.get(id); if(item)item.element.textContent='';widgets.delete(id);},
      getResponse(id) {return widgets.get(id)?.token ?? '';},
      isExpired() {return false;},
    };
    const callback = new URL(document.currentScript.src).searchParams.get('onload');
    window[callback]?.();
  `}));
}
