import { z } from "zod";

const count = z.number().int().min(0).max(Number.MAX_SAFE_INTEGER);
const session = z.string().regex(/^(?!0000)\d{4}-\d{2}-\d{2}$/).refine((value) => {
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
});
const gapSchema = z.object({
  category: z.enum(["年报", "半年报", "一季报", "三季报", "补充更正"]),
  start_date: session,
  end_date: session,
  failure_code: z.enum(["CNINFO_DISCOVERY_UNAVAILABLE", "CNINFO_DISCOVERY_INVALID"]),
}).strict().refine((gap) => gap.start_date <= gap.end_date);
const progressSchema = z.object({
  phase: z.enum(["queued", "preparing", "discovery", "collection", "publication", "finished"]),
  elapsed_seconds: count.nullable(),
  last_progress_at: z.string().datetime({ offset: true }).nullable(),
  discovered_announcement_count: count.nullable(),
  processed_company_count: count.nullable(),
  updated_company_count: count.nullable(),
  unchanged_company_count: count.nullable(),
  failed_company_count: count.nullable(),
  discovery_gaps: z.array(gapSchema).max(5).nullable(),
}).strict().refine((value) => {
  const counts = [value.processed_company_count, value.updated_company_count,
    value.unchanged_company_count, value.failed_company_count];
  return counts.every((item) => item === null) || (
    counts.every((item) => item !== null)
    && value.processed_company_count === Number(value.updated_company_count)
      + Number(value.unchanged_company_count) + Number(value.failed_company_count)
  );
});

export type FinancialRefreshProgress = NonNullable<ReturnType<typeof decodeFinancialRefreshProgress>>;

export function decodeFinancialRefreshProgress(value: unknown) {
  if (value === null) return null;
  const progress = progressSchema.parse(value);
  return {
    phase: progress.phase,
    elapsedSeconds: progress.elapsed_seconds,
    lastProgressAt: progress.last_progress_at,
    discoveredAnnouncementCount: progress.discovered_announcement_count,
    processedCompanyCount: progress.processed_company_count,
    updatedCompanyCount: progress.updated_company_count,
    unchangedCompanyCount: progress.unchanged_company_count,
    failedCompanyCount: progress.failed_company_count,
    discoveryGaps: progress.discovery_gaps?.map((gap) => ({
      category: gap.category,
      startDate: gap.start_date,
      endDate: gap.end_date,
      failureCode: gap.failure_code,
    })) ?? null,
  };
}
