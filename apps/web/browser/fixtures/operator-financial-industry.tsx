import "../../src/styles.css";
import { createRoot } from "react-dom/client";
import { changeInterfaceLanguage, interfaceLocale } from "../../src/i18n";
import { OperatorFinancialRefreshPanel, FinancialRefreshReceipt } from "../../src/operator/OperatorFinancialRefreshPanel";
import { OperatorIndustryRefreshPanel, IndustryRefreshReceipt } from "../../src/operator/OperatorIndustryRefreshPanel";
import type { FinancialRefreshOperation, IndustryRefreshOperation } from "../../src/operator/operatorMutationClient";
import { LanguageControls } from "./language-controls";

const financial: FinancialRefreshOperation = {
  idempotencyKey: "financial-fixture-long-" + "x".repeat(80), kind: "financial",
  observationThroughSession: "2026-08-14", status: "running", outcome: null,
  attemptCount: 1, dataThroughSession: null, failureCode: null,
  lastFailureCode: null, lastRefreshAt: null, financialCompleteThroughSession: null,
  matchedTriggerCount: null, checkedNoStructuredChangeCount: null,
  acceptedInstrumentCount: null, failedInstrumentCount: null,
  pendingInstrumentCount: 2, discoveryGapCount: null,
  progress: {
    phase: "collection", elapsedSeconds: 42, lastProgressAt: null,
    disclosedReportCount: null, processedCompanyCount: 0, updatedCompanyCount: 0,
    unchangedCompanyCount: 0, failedCompanyCount: 1,
    indicatorScheduledCount: null, indicatorCollectedCount: 0,
    indicatorFailedCount: null, indicatorCandidateStatus: "not_started",
    indicatorRetainedReason: "INDICATOR_COVERAGE_UNAVAILABLE",
    discoveryGaps: [{ reportPeriod: "2026-06-30", failureCode: "UPSTREAM_UNAVAILABLE" }],
  },
};
const industry: IndustryRefreshOperation = {
  idempotencyKey: "industry-fixture", kind: "industry",
  observationThroughSession: "2026-08-14", status: "succeeded",
  outcome: "no_change", attemptCount: 1, dataThroughSession: "2026-08-14",
  failureCode: null, lastFailureCode: null, lastRefreshAt: "2026-08-14T10:00:00Z",
};

window.addEventListener("keydown", event => {
  if (event.ctrlKey && event.shiftKey && event.key.toLowerCase() === "l") {
    void changeInterfaceLanguage(interfaceLocale() === "en" ? "zh-CN" : "en");
  }
});

function Fixture() {
  return <><LanguageControls /><main className="mx-auto grid max-w-[1440px] gap-8 p-4">
    <OperatorFinancialRefreshPanel onAccessNotFound={() => undefined} />
    <FinancialRefreshReceipt operation={financial} pollError={false} />
    <OperatorIndustryRefreshPanel onAccessNotFound={() => undefined} />
    <IndustryRefreshReceipt operation={industry} pollError={false} />
  </main></>;
}

createRoot(document.getElementById("root")!).render(<Fixture />);
