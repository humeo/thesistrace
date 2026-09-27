import "../../src/styles.css";
import { createRoot } from "react-dom/client";
import { useRef, useState } from "react";
import { CalendarDateField } from "../../src/components/layout/CalendarDateField";
import { Button } from "../../src/components/ui/button";
import { changeInterfaceLanguage, interfaceLocale, useTranslation } from "../../src/i18n";
import { OperatorDatasetStatusView, OperatorDataStatusDrawer } from "../../src/operator/OperatorDatasetStatus";
import { OperatorMarketRefreshDialog } from "../../src/operator/OperatorMarketRefreshDialog";
import type { DataRefreshOperationalStatus, DatasetOperationalStatus } from "../../src/operator/operatorDataStatusClient";
import { LanguageControls } from "./language-controls";

const key = `market-${"long".repeat(35)}`;
const operation: DataRefreshOperationalStatus = {
  idempotencyKey: key, kind: "market", status: "accepted", outcome: null,
  asOf: "2026-08-14T18:00:00+08:00", observationThroughSession: null, phase: null,
  attemptCount: 0, lastHeartbeatAt: null, dataThroughSession: null, lastRefreshAt: null,
  financialCompleteThroughSession: null, matchedTriggerCount: null,
  checkedNoStructuredChangeCount: null, financialProgress: null,
  acceptedInstrumentCount: null, failedInstrumentCount: null,
  pendingInstrumentCount: null, discoveryGapCount: null, failureCode: null,
  lastFailureCode: null, createdAt: "2026-08-30T08:00:00Z", startedAt: null,
  finishedAt: null, updatedAt: "2026-08-30T08:00:00Z",
};
const data: DatasetOperationalStatus = {
  head: {
    dataIdentity: "d".repeat(64), preparedAt: "2026-08-29T23:00:00Z",
    dataThroughSession: "2026-08-29", marketResearchReadiness: true,
    benchmarkResearchReadiness: true, financialResearchReadiness: "ready_with_pending",
    industryResearchReadiness: true, marketCoverageStart: "2015-01-05",
    marketLastRefreshAt: "2026-08-29T08:00:00Z",
    benchmarkCoverageStart: "2010-01-04", benchmarkCoverageEnd: "2026-08-31",
    benchmarkLastPublishedAt: "2026-08-30T08:02:00Z",
    financialCoverageStart: "2015-01-01", financialAttemptedThroughSession: "2026-08-29",
    financialCompleteThroughSession: "2026-08-28", financialLastRefreshAt: "2026-08-29T08:03:00Z",
    financialPendingInstrumentCount: 2, financialIndicatorPendingInstrumentCount: 0,
    financialIndicatorCheckedThroughSession: "2026-08-31",
    financialIndicatorCompleteThroughSession: "2026-08-31",
    financialDiscoveryGapCount: 1, financialEarliestUnresolvedDate: "2026-08-26",
    industryCoverageStart: "2015-01-05", industryObservationThroughSession: "2026-08-29",
    industryLastRefreshAt: "2026-08-29T08:04:00Z",
  },
  worker: { available: true, lastHeartbeatAt: "2026-08-30T08:01:00Z" },
  latestByKind: [operation], operations: [operation], nextCursor: null,
};
window.addEventListener("keydown", event => {
  if (event.ctrlKey && event.shiftKey && event.key.toLowerCase() === "l") {
    void changeInterfaceLanguage(interfaceLocale() === "en" ? "zh-CN" : "en");
  }
});
function Fixture() {
  const { t } = useTranslation("operator");
  const [date, setDate] = useState("2026-08-14");
  const [selected, setSelected] = useState<DataRefreshOperationalStatus | null>(null);
  const [confirmation, setConfirmation] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const confirmationTrigger = useRef<HTMLButtonElement | null>(null);
  return <><LanguageControls /><main style={{ padding: 16, maxWidth: 1440, marginInline: "auto" }}>
    <CalendarDateField id="as-of" label={t("data.common.asOf")} openLabel={t("data.market.openAsOfCalendar")}
      value={date} minimum={null} maximum={null} errorId="as-of-error" onChange={setDate} />
    <Button ref={confirmationTrigger} onClick={() => setConfirmation(true)}>Review market confirmation</Button>
    <Button variant="outline" onClick={() => setLoading(value => !value)}>Toggle loading</Button>
    <Button variant="outline" onClick={() => setError(value => !value)}>Toggle error</Button>
    <OperatorDatasetStatusView cursorDepth={0} data={data} error={error} loading={loading}
      onDetails={(item, button) => { trigger.current = button; setSelected(item); }}
      onNext={() => undefined} onPrevious={() => undefined} onReload={() => undefined}
      onAction={() => undefined} />
    {selected && <OperatorDataStatusDrawer operation={selected} onAction={() => undefined}
      onDismiss={() => { setSelected(null); requestAnimationFrame(() => trigger.current?.focus()); }} />}
    {confirmation && <OperatorMarketRefreshDialog
      request={{ asOf: "2026-08-14T18:00:00+08:00", idempotencyKey: "market-fixture-confirmation" }}
      onDismiss={() => { setConfirmation(false); requestAnimationFrame(() => confirmationTrigger.current?.focus()); }}
      onRequestRejected={() => undefined} onSubmissionFailed={() => undefined}
      onSubmissionUncertain={() => undefined} onSucceeded={() => undefined} />}
  </main></>;
}
createRoot(document.getElementById("root")!).render(<Fixture />);
