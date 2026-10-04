import { describe, expect, it } from "vitest";

import { calendarDateFromIso, isoFromCalendarDate, isIsoCalendarDate } from "../components/layout/calendarDate";
import { emptyResearchDraft, loadResearchDraftState, researchDraftKey, researchInputIssues } from "./draft";

describe("research dates", () => {
  it("rejects impossible and partially typed calendar dates before admission", () => {
    const valid = {
      ...emptyResearchDraft(),
      formula: "close",
      startDate: "2024-02-29",
      endDate: "2024-03-01",
      universe: "top300",
      neutralization: "none",
    };
    expect(researchInputIssues(valid)).toEqual([]);
    expect(researchInputIssues({ ...valid, startDate: "2025-02-29" })).toContainEqual({
      field: "startDate", code: "startInvalid",
    });
    expect(researchInputIssues({ ...valid, endDate: "2024-0" })).toContainEqual({
      field: "endDate", code: "endInvalid",
    });
    expect(researchInputIssues({ ...valid, startDate: "" })).toContainEqual({
      field: "startDate", code: "startRequired",
    });
  });

  it("round-trips local calendar days without UTC conversion", () => {
    expect(isIsoCalendarDate("2024-02-29")).toBe(true);
    expect(isIsoCalendarDate("2025-02-29")).toBe(false);
    expect(calendarDateFromIso("2025-02-29")).toBeUndefined();
    const day = calendarDateFromIso("2024-02-29");
    expect(day).toBeInstanceOf(Date);
    expect(isoFromCalendarDate(day!)).toBe("2024-02-29");
  });

  it("does not report a malformed stored draft as restored", () => {
    const key = researchDraftKey("owner", "folder");
    const storage = { getItem: (requested: string) => requested === key ? "{broken" : null };
    expect(loadResearchDraftState(storage, "owner", "folder")).toEqual({
      draft: emptyResearchDraft(), restored: false, view: "types",
    });
  });
});
