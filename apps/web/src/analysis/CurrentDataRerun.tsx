import { useRef, useState } from "react";
import { coreFetch } from "../auth/coreFetch";
import { useTranslation } from "../i18n";
import { readResearchIssues, formatResearchIssue, researchIssueField, type ResearchRunAdmissionIssue } from "../research/admission";

export type RerunSource =
  | { kind: "research_run"; run_id: string }
  | { kind: "daily_track"; track_id: string; checkpoint_manifest_sha256: string; through_session: string };

export function CurrentDataRerun({ source, folderId, navigate = path => window.location.assign(path) }: {
  source: RerunSource; folderId: string; navigate?: (path: string) => void;
}) {
  const { t } = useTranslation("analysis");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<"unavailable" | ResearchRunAdmissionIssue[] | null>(null);
  const pending = useRef<{ key: string; request_id: string } | null>(null);
  const inFlight = useRef(false);
  async function submit() {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true); setError(null);
    const key = JSON.stringify({ source, folderId });
    if (pending.current?.key !== key) pending.current = { key, request_id: crypto.randomUUID() };
    try {
      const response = await coreFetch("/api/research-runs", {
        method: "POST", body: JSON.stringify({
          request_id: pending.current.request_id, folder_id: folderId, rerun_source: source,
        }),
      });
      const result = await response.json() as { id?: unknown; issues?: unknown };
      if (!response.ok || typeof result.id !== "string" || !result.id) {
        const issues = response.status === 422 ? readResearchIssues(result.issues) : [];
        setError(issues.length ? issues : "unavailable");
        return;
      }
      navigate(`/research-runs/${encodeURIComponent(result.id)}`);
    } catch {
      setError("unavailable");
    } finally {
      inFlight.current = false; setBusy(false);
    }
  }
  return <div className="daily-holdings-rerun">
    <p>{t("rerun.explanation")}
      {source.kind === "daily_track" && <> {t("rerun.period", { date: source.through_session })}</>}</p>
    <button type="button" disabled={busy} onClick={() => void submit()}>{t(busy ? "rerun.submitting" : "rerun.submit")}</button>
    {error && <p role="alert">{error === "unavailable" ? t("rerun.error") : error.map(issue => `${researchIssueField(issue.field)}: ${formatResearchIssue(issue)}`).join("; ")}</p>}
  </div>;
}

export type RerunOrigin = {
  source_run_id: string; source_track_id?: string | null;
  source_data_generation_id: string; source_checkpoint_manifest_sha256?: string | null;
};
export function CurrentDataRerunOrigin({ origin }: { origin: RerunOrigin }) {
  const { t } = useTranslation("analysis");
  return <p className="research-run-rerun-origin">
    {t("rerun.origin")} · {origin.source_track_id
      ? <a href={`/daily-tracks/${encodeURIComponent(origin.source_track_id)}`}>{t("rerun.sourceTrack")}</a>
      : <a href={`/research-runs/${encodeURIComponent(origin.source_run_id)}`}>{t("rerun.sourceRun")}</a>}
    . {t("rerun.different")}
  </p>;
}
