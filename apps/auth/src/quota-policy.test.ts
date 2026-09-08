import { expect, it } from "vitest";
import { ResearcherQuotaPolicy } from "./quota-policy.js";

it("resolves every limit and the day boundary from one configuration", async () => {
  const policy = new ResearcherQuotaPolicy(async () => false, {
    timezone: "America/New_York", daily_model_budget_usd: 0.25,
    daily_run_limit: 3, active_daily_track_limit: 2,
  });
  expect(await policy.forResearcher("researcher")).toEqual({
    timezone: "America/New_York", daily_model_budget_nanodollars: 250_000_000,
    daily_run_limit: 3, active_daily_track_limit: 2,
  });
});

it("interprets live Operator changes centrally and preserves zero limits", async () => {
  let operator = true;
  const policy = new ResearcherQuotaPolicy(async () => operator, {
    timezone: "Asia/Shanghai", daily_model_budget_usd: 0,
    daily_run_limit: 0, active_daily_track_limit: 0,
  });
  expect(await policy.forResearcher("researcher")).toEqual({
    timezone: "Asia/Shanghai", daily_model_budget_nanodollars: null,
    daily_run_limit: null, active_daily_track_limit: null,
  });
  operator = false;
  expect(await policy.forResearcher("researcher")).toEqual({
    timezone: "Asia/Shanghai", daily_model_budget_nanodollars: 0,
    daily_run_limit: 0, active_daily_track_limit: 0,
  });
});

it("rejects missing, malformed, or inexact configuration before serving requests", () => {
  const rules = { timezone: "Asia/Shanghai", daily_model_budget_usd: 1,
    daily_run_limit: 10, active_daily_track_limit: 10 };
  for (const value of [{}, { ...rules, daily_run_limit: -1 },
    { ...rules, daily_model_budget_usd: 0.0000000001 }, { ...rules, timezone: "invalid" },
    { ...rules, daily_run_limit: 1.1 }, { ...rules, unexpected: true }]) {
    expect(() => new ResearcherQuotaPolicy(async () => false, value)).toThrow();
  }
});
