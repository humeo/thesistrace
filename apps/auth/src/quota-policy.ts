import { z } from "zod";
import configuration from "./quota-policy.config.json" with { type: "json" };

export const planKeySchema = z.enum(["free", "pro", "max"]);
export type PlanKey = z.infer<typeof planKeySchema>;
const planSchema = z.object({
  monthly_price_usd: z.number().int().nonnegative(),
  daily_model_budget_usd: z.number().nonnegative().refine(value =>
    Number.isSafeInteger(Math.round(value * 1_000_000_000))
      && Number(value.toFixed(9)) === value, "Model budget must use exact nanodollars"),
  daily_run_limit: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER),
  active_daily_track_limit: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER),
}).strict();
const rulesSchema = z.object({
  timezone: z.string().refine(value => {
    try { new Intl.DateTimeFormat("en", { timeZone: value }); return true; }
    catch { return false; }
  }, "Invalid quota timezone"),
  plans: z.object({free: planSchema, pro: planSchema, max: planSchema}).strict(),
}).strict();
export const planConfiguration = rulesSchema.parse(configuration);

export type ResearcherQuota = Readonly<{
  timezone: string;
  daily_model_budget_nanodollars: number | null;
  daily_run_limit: number | null;
  active_daily_track_limit: number | null;
}>;

/** Resolves paid entitlements without owning or resetting resource consumption. */
export class ResearcherQuotaPolicy {
  private readonly rules: z.infer<typeof rulesSchema>;

  constructor(private readonly isOperator: (researcherId: string) => Promise<boolean>,
    private readonly researcherPlan: (researcherId: string) => Promise<PlanKey>,
    rules: unknown = configuration) {
    this.rules = rulesSchema.parse(rules);
  }

  async forResearcher(researcherId: string): Promise<ResearcherQuota> {
    const unlimited = await this.isOperator(researcherId);
    const plan = this.rules.plans[planKeySchema.parse(await this.researcherPlan(researcherId))];
    return {
      timezone: this.rules.timezone,
      daily_model_budget_nanodollars: unlimited ? null : Math.round(plan.daily_model_budget_usd * 1_000_000_000),
      daily_run_limit: unlimited ? null : plan.daily_run_limit,
      active_daily_track_limit: unlimited ? null : plan.active_daily_track_limit,
    };
  }
}
