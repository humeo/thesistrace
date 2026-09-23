import { i18n, interfaceLocale } from "./index";

type MissingValue = "notAvailable" | "dash";
const missingValue = (missing: MissingValue) => missing === "dash" ? "—" : i18n.t("common:notAvailable");

/** Presentation only: callers retain the original numeric value for requests and exports. */
export function formatNumber(value: number, options: Intl.NumberFormatOptions = {}): string {
  return new Intl.NumberFormat(interfaceLocale(), options).format(value);
}

export function formatDecimal(value: number | null, digits = 3, missing: MissingValue = "notAvailable", signed = false): string {
  if (value === null) return missingValue(missing);
  // Retain the existing toFixed rounding, including tiny negative values and positive signs.
  const rounded = Number(value.toFixed(digits));
  return (signed && value > 0 ? "+" : "") + formatNumber(rounded, {
    minimumFractionDigits: digits, maximumFractionDigits: digits, useGrouping: false,
  });
}

export function formatPercent(value: number | null, { signed = false, missing = "notAvailable" }: { signed?: boolean; missing?: MissingValue } = {}): string {
  return value === null ? missingValue(missing) : `${formatDecimal(value * 100, 2, missing, signed)}%`;
}

export function formatCurrency(value: number, digits = 2): string {
  return formatNumber(value, { style: "currency", currency: "CNY", minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** A Research Session is a calendar date, never a browser-local instant. */
export function formatSessionDate(value: string): string {
  return new Intl.DateTimeFormat(interfaceLocale(), { year: "numeric", month: "2-digit", day: "2-digit", timeZone: "UTC" })
    .format(new Date(`${value}T00:00:00Z`));
}

/** Callers explicitly retain UTC or browser-local semantics. Undefined timeZone means local. */
export function formatTimestamp(value: string | null, options: Intl.DateTimeFormatOptions = { timeZone: "UTC", dateStyle: "medium", timeStyle: "medium" }): string {
  if (value === null) return missingValue("notAvailable");
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? missingValue("notAvailable") : new Intl.DateTimeFormat(interfaceLocale(), options).format(date);
}

/** Existing execution tables use sortable ISO dates and whole seconds in UTC in both languages. */
export function formatUtcTimestamp(value: string | null, showZone = false): string {
  if (value === null) return missingValue("notAvailable");
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? missingValue("notAvailable") : date.toISOString().replace("T", " ").slice(0, 19) + (showZone ? " UTC" : "");
}

export function formatDuration(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return i18n.t("common:notStarted");
  const rounded = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.floor((rounded % 3600) / 60);
  const remainder = rounded % 60;
  if (hours > 0) return i18n.t("common:durationHours", { hours: formatNumber(hours), minutes: formatNumber(minutes), seconds: formatNumber(remainder) });
  if (minutes > 0) return i18n.t("common:durationMinutes", { minutes: formatNumber(minutes), seconds: formatNumber(remainder) });
  return i18n.t("common:durationSeconds", { seconds: formatNumber(remainder) });
}
