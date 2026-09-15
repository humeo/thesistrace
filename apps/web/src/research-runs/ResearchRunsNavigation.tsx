import { followCoreLink } from "../shell/navigation";

export function ResearchRunsNavigation({ active }: { active: "runs" | "batches" }) {
  return (
    <nav aria-label="Research history" className="research-history-navigation">
      <a aria-current={active === "runs" ? "page" : undefined} href="/research-runs" onClick={followCoreLink}>Runs</a>
      <a aria-current={active === "batches" ? "page" : undefined} href="/research-runs/batches" onClick={followCoreLink}>Batches</a>
    </nav>
  );
}
