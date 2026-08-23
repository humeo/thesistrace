export type ResearchDatePreset = {
  label: "1Y" | "3Y" | "5Y" | "Max";
  accessibleLabel: string;
  startDate: string | null;
  endDate: string | null;
};

const RESEARCH_DATE_HORIZONS = [
  { label: "1Y", accessibleLabel: "Use last 1 year", years: 1 },
  { label: "3Y", accessibleLabel: "Use last 3 years", years: 3 },
  { label: "5Y", accessibleLabel: "Use last 5 years", years: 5 },
] as const;

export function buildResearchDatePresets(
  coverageStart: string | null,
  coverageEnd: string | null,
): ResearchDatePreset[] {
  const coverage = coverageStart !== null &&
    coverageEnd !== null &&
    isIsoDate(coverageStart) &&
    isIsoDate(coverageEnd) &&
    coverageStart <= coverageEnd
    ? { startDate: coverageStart, endDate: coverageEnd }
    : null;

  const horizonPresets = RESEARCH_DATE_HORIZONS.map(({ label, accessibleLabel, years }) => {
    const candidate = coverage === null ? null : subtractCalendarYears(coverage.endDate, years);
    const available = candidate !== null && coverage !== null && candidate > coverage.startDate;
    return {
      label,
      accessibleLabel,
      startDate: available ? candidate : null,
      endDate: available ? coverage.endDate : null,
    };
  });

  return [
    ...horizonPresets,
    {
      label: "Max",
      accessibleLabel: "Use all available data",
      startDate: coverage?.startDate ?? null,
      endDate: coverage?.endDate ?? null,
    },
  ];
}

function isIsoDate(value: string): boolean {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (match === null) return false;
  const [, yearText, monthText, dayText] = match;
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year &&
    date.getUTCMonth() === month - 1 &&
    date.getUTCDate() === day;
}

function subtractCalendarYears(value: string, years: number): string | null {
  if (!isIsoDate(value)) return null;
  const [year, month, day] = value.split("-").map(Number);
  const targetYear = year - years;
  const finalDay = Math.min(day, new Date(Date.UTC(targetYear, month, 0)).getUTCDate());
  return `${String(targetYear).padStart(4, "0")}-${String(month).padStart(2, "0")}-${String(finalDay).padStart(2, "0")}`;
}
