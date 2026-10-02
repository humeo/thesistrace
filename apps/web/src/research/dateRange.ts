import { isIsoCalendarDate } from "../components/layout/calendarDate";

export type ResearchDatePreset = {
  id: "1Y" | "3Y" | "5Y" | "Max";
  startDate: string | null;
  endDate: string | null;
};

const RESEARCH_DATE_HORIZONS = [
  { id: "1Y", years: 1 },
  { id: "3Y", years: 3 },
  { id: "5Y", years: 5 },
] as const;

export function buildResearchDatePresets(
  coverageStart: string | null,
  coverageEnd: string | null,
  selectedEndDate?: string,
): ResearchDatePreset[] {
  const coverage = coverageStart !== null &&
    coverageEnd !== null &&
    isIsoCalendarDate(coverageStart) &&
    isIsoCalendarDate(coverageEnd) &&
    coverageStart <= coverageEnd
    ? { startDate: coverageStart, endDate: coverageEnd }
    : null;
  const anchor = coverage !== null && selectedEndDate && isIsoCalendarDate(selectedEndDate)
    && selectedEndDate >= coverage.startDate && selectedEndDate <= coverage.endDate
    ? selectedEndDate : coverage?.endDate ?? null;

  const horizonPresets = RESEARCH_DATE_HORIZONS.map(({ id, years }) => {
    const candidate = anchor === null ? null : subtractCalendarYears(anchor, years);
    const available = candidate !== null && coverage !== null && candidate > coverage.startDate;
    return {
      id,
      startDate: available ? candidate : null,
      endDate: available ? anchor : null,
    };
  });

  return [
    ...horizonPresets,
    {
      id: "Max",
      startDate: coverage?.startDate ?? null,
      endDate: coverage?.endDate ?? null,
    },
  ];
}

function subtractCalendarYears(value: string, years: number): string | null {
  if (!isIsoCalendarDate(value)) return null;
  const [year, month, day] = value.split("-").map(Number);
  const targetYear = year - years;
  const finalDay = Math.min(day, new Date(Date.UTC(targetYear, month, 0)).getUTCDate());
  return `${String(targetYear).padStart(4, "0")}-${String(month).padStart(2, "0")}-${String(finalDay).padStart(2, "0")}`;
}
