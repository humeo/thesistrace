import { readFileSync } from "node:fs";
import type { Page } from "@playwright/test";

// Component fixtures use the same local fonts and logo assets as the real entrypoint.
export const fontStylesheet = '<link rel="stylesheet" href="http://assets.fixture/fonts/quantgrove.css">';
const contentTypes: Record<string, string> = {
  css: "text/css", woff2: "font/woff2", svg: "image/svg+xml", png: "image/png", jpg: "image/jpeg",
};

export async function serveBrandAssets(page: Page): Promise<void> {
  await page.route(/\/(?:brand|fonts)\/[a-z0-9-]+\.(?:css|woff2|svg|png|jpg)$/, route => {
    const pathname = new URL(route.request().url()).pathname;
    const extension = pathname.split(".").at(-1)!;
    return route.fulfill({
      contentType: contentTypes[extension],
      headers: { "Access-Control-Allow-Origin": "*" },
      body: readFileSync(new URL(`../public${pathname}`, import.meta.url)),
    });
  });
}
