import { isIsoCalendarDate } from "../components/layout/calendarDate";

export type RetrievalDateRange = { start: string; end: string };
type Dates = { start_session: string; end_session: string };
type DateField = keyof Dates;
export type RetrievalDateError = "invalidDate" | "invalidRange" | "outsidePeriod";

export function validateRetrievalDates(dates: Dates, range?: RetrievalDateRange): Partial<Record<DateField, RetrievalDateError>> {
  const errors: Partial<Record<DateField, RetrievalDateError>> = {};
  for (const key of ["start_session", "end_session"] as const) {
    const value = dates[key];
    if (!value) continue;
    if (!isIsoCalendarDate(value)) errors[key] = "invalidDate";
    else if (range && (value < range.start || value > range.end)) errors[key] = "outsidePeriod";
  }
  if (!Object.keys(errors).length && dates.start_session && dates.end_session && dates.start_session > dates.end_session) {
    errors.end_session = "invalidRange";
  }
  return errors;
}

export function retrievalCalendarBounds(key: DateField, dates: Dates, range?: RetrievalDateRange): { minimum: string | null; maximum: string | null } {
  const other = dates[key === "start_session" ? "end_session" : "start_session"];
  const validOther = isIsoCalendarDate(other) && (!range || (other >= range.start && other <= range.end));
  return {
    minimum: key === "end_session" && validOther ? other : range?.start ?? null,
    maximum: key === "start_session" && validOther ? other : range?.end ?? null,
  };
}
