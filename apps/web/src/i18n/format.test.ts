import { afterEach, describe, expect, it } from "vitest";
import { i18n } from "./index";
import { formatCurrency, formatDecimal, formatNumber, formatPercent, formatSessionDate, formatTimestamp, formatUtcTimestamp } from "./format";

afterEach(() => { void i18n.changeLanguage("en"); });

describe("interface formatting", () => {
  it("preserves research precision, signs, missing values and currency in either language", async () => {
    for (const locale of ["en", "zh-CN"]) {
      await i18n.changeLanguage(locale);
      expect(formatDecimal(1.23456)).toBe("1.235");
      expect(formatDecimal(1.005, 2)).toBe("1.00");
      expect(formatPercent(0.123456)).toBe("12.35%");
      expect(formatPercent(0.000001, { signed: true })).toBe("+0.00%");
      expect(formatPercent(-0.000001, { signed: true })).toBe("-0.00%");
      expect(formatPercent(0, { signed: true })).toBe("0.00%");
      expect(formatPercent(null, { missing: "dash" })).toBe("—");
      expect(formatNumber(12345)).toBe("12,345");
      expect(formatCurrency(1234.5, 2)).toContain("1,234.50");
      expect(formatCurrency(1234.5, 0)).toContain("1,235");
      expect(formatDecimal(null)).toBe(locale === "en" ? "Not available" : "不可用");
    }
  });

  it("keeps research dates on their calendar day and timestamps on their explicit timezone", async () => {
    await i18n.changeLanguage("en");
    expect(formatSessionDate("2026-09-22")).toBe("09/22/2026");
    expect(formatUtcTimestamp("2026-09-22T23:15:01.987-07:00")).toBe("2026-09-23 06:15:01");
    expect(formatUtcTimestamp("2026-09-22T23:15:01.987-07:00", true)).toBe("2026-09-23 06:15:01 UTC");
    expect(formatTimestamp("2026-09-23T00:00:00Z", { timeZone: "America/Los_Angeles", dateStyle: "short", timeStyle: undefined })).toBe("9/22/26");
    await i18n.changeLanguage("zh-CN");
    expect(formatSessionDate("2026-09-22")).toBe("2026/09/22");
    expect(formatUtcTimestamp("2026-09-22T23:15:01.987-07:00", true)).toBe("2026-09-23 06:15:01 UTC");
    expect(formatTimestamp(null)).toBe("不可用");
    expect(formatTimestamp("invalid")).toBe("不可用");
  });
});
