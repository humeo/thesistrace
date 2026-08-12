import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ResearchDateFields } from "./DefinitionsPage";
import {
  BROWSER_DRAFT_STORAGE_KEY,
  confirmDraftReplacement,
  persistResearchDraft,
  readResearchDraft,
  storeResearchDraft,
  type ResearchBrowserDraft,
} from "./browserDraft";

describe("ResearchDateFields", () => {
  it("renders independently nullable natural-date inputs and restores saved values", () => {
    const markup = renderToStaticMarkup(
      <ResearchDateFields
        coverageEnd="2026-08-30"
        coverageStart="2025-08-03"
        endDate="2026-03-31"
        onEndDateChange={() => undefined}
        onStartDateChange={() => undefined}
        startDate="2026-01-02"
      />,
    );

    expect(markup).toContain('aria-label="Research start date"');
    expect(markup).toContain('min="2025-08-03"');
    expect(markup).toContain('max="2026-03-31"');
    expect(markup).toContain('value="2026-01-02"');
    expect(markup).toContain('aria-label="Research end date"');
    expect(markup).toContain('min="2026-01-02"');
    expect(markup).toContain('max="2026-08-30"');
    expect(markup).toContain('value="2026-03-31"');
    expect(markup).toContain('Available data: 2025-08-03 to 2026-08-30');
    expect(markup.match(/type="date"/g)).toHaveLength(2);
  });

  it("renders incomplete drafts without inventing date values", () => {
    const markup = renderToStaticMarkup(
      <ResearchDateFields
        coverageEnd="2026-08-30"
        coverageStart="2025-08-03"
        endDate=""
        onEndDateChange={() => undefined}
        onStartDateChange={() => undefined}
        startDate=""
      />,
    );

    expect(markup).not.toMatch(/value="\d{4}-\d{2}-\d{2}"/);
  });

  it("preserves an out-of-coverage draft while explaining why it cannot run", () => {
    const markup = renderToStaticMarkup(
      <ResearchDateFields
        coverageEnd="2026-08-30"
        coverageStart="2025-08-03"
        endDate="2026-09-01"
        onEndDateChange={() => undefined}
        onStartDateChange={() => undefined}
        startDate="2025-08-01"
      />,
    );

    expect(markup).toContain('value="2025-08-01"');
    expect(markup).toContain('value="2026-09-01"');
    expect(markup).toContain("Research period must stay within current Data coverage");
  });
});

describe("Research browser draft", () => {
  const draft: ResearchBrowserDraft = {
    name: "Frozen composite",
    hypothesis: "Financial quality plus momentum",
    start_date: "2026-08-03",
    end_date: "2026-08-30",
    alpha: { operator_id: "cs_rank", operands: [{ field_id: "price.close.adjusted" }] },
    universe: "top300",
    neutralization: "industry",
    holdings_count: "20",
    rebalance_every_sessions: "5",
  };

  it("copies a frozen Run into browser storage and protects an existing draft", () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); },
    };

    expect(storeResearchDraft(draft, storage, () => true)).toBe(true);
    expect(readResearchDraft(storage)).toEqual(draft);
    expect(storeResearchDraft({ ...draft, name: "Replacement" }, storage, () => false)).toBe(false);
    expect(JSON.parse(values.get(BROWSER_DRAFT_STORAGE_KEY)!)).toEqual(draft);
    expect(storeResearchDraft({ ...draft, name: "Replacement" }, storage, () => true)).toBe(true);
    expect(readResearchDraft(storage)?.name).toBe("Replacement");

    persistResearchDraft({ ...draft, holdings_count: "" }, storage);
    expect(readResearchDraft(storage)?.holdings_count).toBe("");
    expect(confirmDraftReplacement(storage, () => false)).toBe(false);
    expect(confirmDraftReplacement(storage, () => true)).toBe(true);
  });
});
