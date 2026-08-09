import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ResearchDateFields } from "./DefinitionsPage";

describe("ResearchDateFields", () => {
  it("renders independently nullable natural-date inputs and restores saved values", () => {
    const markup = renderToStaticMarkup(
      <ResearchDateFields
        endDate="2026-03-31"
        onEndDateChange={() => undefined}
        onStartDateChange={() => undefined}
        startDate="2026-01-02"
      />,
    );

    expect(markup).toContain('aria-label="Research start date"');
    expect(markup).toContain('value="2026-01-02"');
    expect(markup).toContain('aria-label="Research end date"');
    expect(markup).toContain('value="2026-03-31"');
    expect(markup.match(/type="date"/g)).toHaveLength(2);
  });

  it("renders incomplete drafts without inventing date values", () => {
    const markup = renderToStaticMarkup(
      <ResearchDateFields
        endDate=""
        onEndDateChange={() => undefined}
        onStartDateChange={() => undefined}
        startDate=""
      />,
    );

    expect(markup).not.toMatch(/value="\d{4}-\d{2}-\d{2}"/);
  });
});
