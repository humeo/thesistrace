import { createRoot } from "react-dom/client";
import { ResearchDraftWorkspace } from "../../src/research/ResearchWorkspacePage";
import { emptyResearchDraft, persistResearchDraft, researchDraftKey } from "../../src/research/draft";

const researcherId = "exposure-test";
const folder = { id: "folder_default", name: "Default", is_default: true, created_at: "2026-08-01T00:00:00Z" };
if (localStorage.getItem(researchDraftKey(researcherId, folder.id)) === null) {
  persistResearchDraft(localStorage, researcherId, folder.id, {
    ...emptyResearchDraft(), researchKind: "strategy_backtest", formula: "close",
    startDate: "2026-08-03", endDate: "2026-08-05", universe: "top300", neutralization: "none",
    initialCashCny: "100000", holdingsCount: "10", selectionEverySessions: "5",
  });
}
createRoot(document.getElementById("root")!).render(<ResearchDraftWorkspace
  researcherId={researcherId} folder={folder} catalog={{ fields: [], builtins: [], industries: [] }}
  data={{
    market_coverage: { start: "2025-01-01", end: "2026-08-12" }, financial_coverage: null,
    industry_coverage: null, benchmark_coverage: null, benchmark_snapshot_sha256: null,
    benchmark_last_published_at: null, data_through_session: "2026-08-12",
    last_market_refresh_at: "2026-08-13T00:00:00Z", last_financial_refresh_at: null,
    last_industry_refresh_at: null, industry_refresh_status: null, industry_refresh_failure_code: null,
    market_research_readiness: true, benchmark_research_readiness: false,
    financial_research_readiness: "not_ready", industry_research_readiness: false,
  }}
/>);
