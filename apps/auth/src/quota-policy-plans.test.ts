import { expect, it } from "vitest";
import { ResearcherQuotaPolicy } from "./quota-policy.js";

it("applies the Researcher's current paid plan without resetting the shared quota day", async () => {
  let plan: "free" | "pro" | "max" = "free";
  const policy = new ResearcherQuotaPolicy(
    async () => false,
    async () => plan,
  );
  expect(await policy.forResearcher("researcher")).toEqual({
    timezone: "Asia/Shanghai",
    daily_model_budget_nanodollars: 1_000_000_000,
    daily_run_limit: 10,
    active_daily_track_limit: 1,
  });
  plan = "pro";
  expect(await policy.forResearcher("researcher")).toEqual({
    timezone: "Asia/Shanghai",
    daily_model_budget_nanodollars: 1_500_000_000,
    daily_run_limit: 100,
    active_daily_track_limit: 10,
  });
  plan = "max";
  expect(await policy.forResearcher("researcher")).toEqual({
    timezone: "Asia/Shanghai",
    daily_model_budget_nanodollars: 2_000_000_000,
    daily_run_limit: 500,
    active_daily_track_limit: 50,
  });
  plan = "free";
  expect(
    (await policy.forResearcher("researcher")).active_daily_track_limit,
  ).toBe(1);
});
