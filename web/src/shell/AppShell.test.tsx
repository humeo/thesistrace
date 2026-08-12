import { expect, test } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { AppShell } from "./AppShell";

test("renders four resources and composes only the active resource content", () => {
  const markup = renderToStaticMarkup(
    <AppShell currentPath="/research-runs">
      <section aria-label="Active resource">Selected resource</section>
    </AppShell>,
  );

  expect(markup.match(/<a /g)).toHaveLength(5);
  expect(markup).toContain('href="/data"');
  expect(markup).toContain('href="/research"');
  expect(markup).not.toContain("Definitions");
  expect(markup).toContain('aria-current="page" href="/research-runs"');
  expect(markup).toContain('href="/daily-tracks"');
  expect(markup).toContain('href="/research?new"');
  expect(markup).toContain("New Research");
  expect(markup).toContain("Selected resource");
});
