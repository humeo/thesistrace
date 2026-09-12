import { createRoot } from "react-dom/client";
import { DailyHoldings } from "../../src/analysis/DailyHoldings";
import { CurrentDataRerunOrigin, type RerunSource } from "../../src/analysis/CurrentDataRerun";
const track = new URLSearchParams(window.location.search).has("track");
const source: RerunSource = track
  ? { kind: "daily_track", track_id: "track_holdings", checkpoint_manifest_sha256: "a".repeat(64), through_session: "2026-08-10" }
  : { kind: "research_run", run_id: "run_holdings" };
createRoot(document.getElementById("root")!).render(<main style={{ padding: 24 }}>
  <CurrentDataRerunOrigin origin={{ source_run_id: "run_original", source_data_generation_id: "original_data" }} />
  <DailyHoldings endpoint="/api/research-runs/run_holdings/holdings/query" rerun={{ folderId: "folder_default", source }} />
</main>);
