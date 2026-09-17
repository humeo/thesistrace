import { z } from "zod";

const count = z.number().int().min(0).max(Number.MAX_SAFE_INTEGER);
const session = z.string().regex(/^(?!0000)\d{4}-\d{2}-\d{2}$/).refine((value) => {
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
});
const gapSchema = z.object({
  report_period: session,
  failure_code: z.string().min(1).max(100),
}).strict();
const progressSchema = z.object({
  phase: z.enum(["queued", "preparing", "discovery", "indicator_collection", "indicator_candidate", "collection", "publication", "finished"]),
  elapsed_seconds: count.nullable(),
  last_progress_at: z.string().datetime({ offset: true }).nullable(),
  disclosed_report_count: count.nullable(),
  processed_company_count: count.nullable(),
  updated_company_count: count.nullable(),
  unchanged_company_count: count.nullable(),
  failed_company_count: count.nullable(),
  indicator_scheduled_count: count.nullable(),
  indicator_collected_count: count.nullable(),
  indicator_failed_count: count.nullable(),
  indicator_candidate_status: z.enum(["not_started", "building", "ready", "retained"]),
  indicator_retained_reason: z.literal("INDICATOR_COVERAGE_UNAVAILABLE").nullable(),
  discovery_gaps: z.array(gapSchema).max(500).nullable(),
}).strict().refine((value) => {
  const counts = [value.processed_company_count, value.updated_company_count,
    value.unchanged_company_count, value.failed_company_count];
  const indicators = [value.indicator_scheduled_count, value.indicator_collected_count,
    value.indicator_failed_count];
  const validIndicators = indicators.every((item) => item === null) || (
    indicators.every((item) => item !== null)
    && value.indicator_scheduled_count === Number(value.indicator_collected_count)
      + Number(value.indicator_failed_count)
  );
  return validIndicators && (counts.every((item) => item === null) || (
    counts.every((item) => item !== null)
    && value.processed_company_count === Number(value.updated_company_count)
      + Number(value.unchanged_company_count) + Number(value.failed_company_count)
  ));
});

export type FinancialRefreshProgress = NonNullable<ReturnType<typeof decodeFinancialRefreshProgress>>;

export function decodeFinancialRefreshProgress(value: unknown) {
  if (value === null) return null;
  const progress = progressSchema.parse(value);
  return {
    phase: progress.phase,
    elapsedSeconds: progress.elapsed_seconds,
    lastProgressAt: progress.last_progress_at,
    disclosedReportCount: progress.disclosed_report_count,
    processedCompanyCount: progress.processed_company_count,
    updatedCompanyCount: progress.updated_company_count,
    unchangedCompanyCount: progress.unchanged_company_count,
    failedCompanyCount: progress.failed_company_count,
    indicatorScheduledCount: progress.indicator_scheduled_count,
    indicatorCollectedCount: progress.indicator_collected_count,
    indicatorFailedCount: progress.indicator_failed_count,
    indicatorCandidateStatus: progress.indicator_candidate_status,
    indicatorRetainedReason: progress.indicator_retained_reason,
    discoveryGaps: progress.discovery_gaps?.map((gap) => ({
      reportPeriod: gap.report_period,
      failureCode: gap.failure_code,
    })) ?? null,
  };
}
