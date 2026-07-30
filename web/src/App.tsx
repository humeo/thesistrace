import "@fontsource-variable/newsreader";
import "@fontsource-variable/space-grotesk";
import {
  Activity,
  Archive,
  ArrowUpRight,
  Database,
  FlaskConical,
  Layers3,
  Radio,
} from "lucide-react";
import { useEffect, useState } from "react";

import "./app.css";

type ResourceCounts = {
  dataset_releases: number;
  research_definitions: number;
  research_runs: number;
  daily_tracks: number;
};

type Workspace = {
  installation_id: string;
  resource_counts: ResourceCounts;
  latest_dataset_release: DatasetRelease | null;
};

type DatasetRelease = {
  id: string;
  predecessor_id: string | null;
  session_count: number;
  instrument_count: number;
  appended_session_range: { start: string; end: string };
  objects: { kind: string; sha256: string; bytes: number }[];
  manifest_sha256: string;
};

type ComponentHealth = {
  status: "available" | "unavailable";
  last_heartbeat_at?: string | null;
};

type Health = {
  status: "available" | "degraded";
  components: {
    database: ComponentHealth;
    object_store: ComponentHealth;
    worker: ComponentHealth;
  };
};

type DataContract = {
  calendar: { session_count: number; start: string; end: string };
  alpha_authorable_fields: string[];
  universes: string[];
  industry_levels: string[];
  trading_state_counts: Record<string, number>;
};

type WorkspaceState =
  | { status: "loading" }
  | { status: "ready"; workspace: Workspace; health: Health }
  | { status: "error" };

const resources = [
  { key: "dataset_releases", label: "Dataset Releases", icon: Database },
  { key: "research_definitions", label: "Research Definitions", icon: FlaskConical },
  { key: "research_runs", label: "Research Runs", icon: Activity },
  { key: "daily_tracks", label: "Daily Tracks", icon: Radio },
] as const;

export default function App() {
  const [state, setState] = useState<WorkspaceState>({ status: "loading" });
  const [publication, setPublication] = useState<"idle" | "running" | "failed">("idle");

  useEffect(() => {
    const controller = new AbortController();

    Promise.all([
      fetch("/api/v1/workspace", { signal: controller.signal }).then(assertResponse),
      fetch("/api/v1/health", { signal: controller.signal }).then(assertResponse),
    ])
      .then(async ([workspaceResponse, healthResponse]) => {
        const [workspace, health] = await Promise.all([
          workspaceResponse.json() as Promise<Workspace>,
          healthResponse.json() as Promise<Health>,
        ]);
        setState({ status: "ready", workspace, health });
      })
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setState({ status: "error" });
        }
      });

    return () => controller.abort();
  }, []);

  async function bootstrapFixture() {
    if (state.status !== "ready") {
      return;
    }
    setPublication("running");
    try {
      const response = await fetch("/api/v1/dataset-releases/bootstrap", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": "workspace-bootstrap-fixture-v1",
        },
        body: JSON.stringify({ fixture: "v1" }),
      }).then(assertResponse);
      const payload = (await response.json()) as { release: DatasetRelease };
      setState({
        status: "ready",
        health: state.health,
        workspace: {
          ...state.workspace,
          latest_dataset_release: payload.release,
          resource_counts: {
            ...state.workspace.resource_counts,
            dataset_releases: 1,
          },
        },
      });
      setPublication("idle");
    } catch {
      setPublication("failed");
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="wordmark" href="/" aria-label="ThesisTrace 首页">
          <span className="wordmark-mark">TT</span>
          <span>ThesisTrace</span>
        </a>
        <div className="edition">A-SHARE RESEARCH LEDGER · V1</div>
        <div className="system-state">
          <span className={`pulse ${state.status === "ready" ? "is-live" : ""}`} />
          {state.status === "ready" ? "WORKSPACE ONLINE" : "CONNECTING"}
        </div>
      </header>

      <aside className="side-rail" aria-label="主导航">
        <a className="rail-link active" href="#workspace">
          <Layers3 size={17} aria-hidden="true" />
          工作台
        </a>
        <span className="rail-rule" />
        <div className="rail-meta">
          <span>MODE</span>
          <strong>POST-CLOSE</strong>
        </div>
        <div className="rail-meta">
          <span>MARKET</span>
          <strong>SSE · SZSE</strong>
        </div>
        <div className="rail-foot">单节点 · 单操作者</div>
      </aside>

      <main id="workspace" className="workspace">
        <section className="hero">
          <p className="eyebrow">RESEARCH CONTROL / 研究控制面</p>
          <h1>研究工作台</h1>
          <p className="hero-copy">
            从不可变数据版本出发，让 Alpha、因子评估、策略回测和每日追踪共享同一条证据链。
          </p>
          <div className="hero-index" aria-hidden="true">
            00
          </div>
        </section>

        {state.status === "loading" && <StatusPanel message="正在读取 Workspace 元数据…" />}
        {state.status === "error" && (
          <StatusPanel
            message="Workspace API 暂不可用"
            detail="页面不会用示例数据代替真实资源。请检查 API、Metadata 与 Worker。"
            tone="error"
          />
        )}
        {state.status === "ready" && (
          <>
            <section className="resource-strip" aria-label="Workspace 资源">
              {resources.map(({ key, label, icon: Icon }, index) => (
                <div className="resource-cell" role="group" aria-label={label} key={key}>
                  <div className="cell-head">
                    <Icon size={16} strokeWidth={1.7} aria-hidden="true" />
                    <span>{label}</span>
                  </div>
                  <div className="resource-value">{state.workspace.resource_counts[key]}</div>
                  <div className="cell-index">0{index + 1}</div>
                </div>
              ))}
            </section>

            <div className="workspace-grid">
              <section className="release-panel">
                <div className="section-heading">
                  <div>
                    <p className="eyebrow">CURRENT DATA TRUTH</p>
                    <h2>数据版本</h2>
                  </div>
                  <Archive size={21} strokeWidth={1.6} aria-hidden="true" />
                </div>
                {state.workspace.latest_dataset_release === null ? (
                  <div className="empty-release">
                    <div className="empty-coordinate">∅</div>
                    <div>
                      <h3>尚未发布数据版本</h3>
                      <p>
                        Bootstrap Release 发布后，这里会显示固定日历、Universe、标准字段和复权锚点。
                      </p>
                      <button
                        className="bootstrap-button"
                        type="button"
                        onClick={bootstrapFixture}
                        disabled={publication === "running"}
                      >
                        {publication === "running" ? "正在发布…" : "发布 Fixture Bootstrap"}
                        <ArrowUpRight size={16} aria-hidden="true" />
                      </button>
                      {publication === "failed" && (
                        <p className="publication-error" role="alert">
                          发布失败；latest 数据版本未改变。
                        </p>
                      )}
                    </div>
                  </div>
                ) : (
                  <ReleaseSummary release={state.workspace.latest_dataset_release} />
                )}
                <div className="truth-note">
                  <span>TRUTH POLICY</span>
                  <strong>只展示已发布、可追溯的资源</strong>
                </div>
              </section>

              <section className="health-panel">
                <div className="section-heading">
                  <div>
                    <p className="eyebrow">DEPENDENCY REGISTER</p>
                    <h2>系统依赖</h2>
                  </div>
                  <span className={`overall ${state.health.status}`}>
                    {state.health.status === "available" ? "ALL CLEAR" : "DEGRADED"}
                  </span>
                </div>
                <HealthRow label="API / Metadata" health={state.health.components.database} />
                <HealthRow label="Object Store" health={state.health.components.object_store} />
                <HealthRow label="Worker" health={state.health.components.worker} />
              </section>
            </div>

            {state.workspace.latest_dataset_release && (
              <DataContractPanel releaseId={state.workspace.latest_dataset_release.id} />
            )}

            <footer className="workspace-footer">
              <div>
                <span className="footer-label">INSTALLATION</span>
                <code>{state.workspace.installation_id}</code>
              </div>
              <div className="integrity">
                <span>没有伪造示例资源</span>
                <ArrowUpRight size={16} aria-hidden="true" />
              </div>
            </footer>
          </>
        )}
      </main>
    </div>
  );
}

function DataContractPanel({ releaseId }: { releaseId: string }) {
  const [contract, setContract] = useState<DataContract | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch(`/api/v1/dataset-releases/${releaseId}/data-contract`, {
      signal: controller.signal,
    })
      .then(assertResponse)
      .then((response) => response.json() as Promise<DataContract>)
      .then(setContract)
      .catch(() => setContract(null));
    return () => controller.abort();
  }, [releaseId]);

  if (contract === null) {
    return null;
  }

  const universeLabel = ["top300", "top1000", "top2000", "top3000"]
    .filter((name) => contract.universes.includes(name))
    .map((name) => `TOP ${name.slice(3)}`)
    .join(" · ");

  return (
    <section className="contract-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">CANONICAL RESEARCH SURFACE</p>
          <h2>标准研究数据契约</h2>
        </div>
        <span className="contract-version">EOD · V1</span>
      </div>
      <div className="contract-grid">
        <div className="contract-block fields">
          <span>ALPHA FIELDS</span>
          <div className="field-chips">
            {contract.alpha_authorable_fields.map((field) => (
              <code key={field}>{field}</code>
            ))}
          </div>
        </div>
        <div className="contract-block">
          <span>RESEARCH CALENDAR</span>
          <strong>{contract.calendar.session_count} SESSION INTERSECTION</strong>
          <small>
            {contract.calendar.start} → {contract.calendar.end}
          </small>
        </div>
        <div className="contract-block">
          <span>LIQUIDITY UNIVERSES</span>
          <strong>{universeLabel}</strong>
          <small>20-session mean turnover · deterministic ties</small>
        </div>
        <div className="contract-block">
          <span>INDUSTRY MEMBERSHIP</span>
          <strong>SW2021 L1 · L2 · L3</strong>
          <small>point-in-time half-open intervals</small>
        </div>
        <div className="contract-block">
          <span>TRADING STATE EVIDENCE</span>
          <strong>
            FULL SESSION SUSPENSION ·{" "}
            {contract.trading_state_counts.full_session_suspension ?? 0}
          </strong>
          <small>normal · partial opening · after open · full session</small>
        </div>
      </div>
    </section>
  );
}

function ReleaseSummary({ release }: { release: DatasetRelease }) {
  return (
    <div className="release-summary">
      <div className="release-lead">
        <span className="release-status">PUBLISHED</span>
        <div>
          <h3>Fixture Bootstrap 已发布</h3>
          <code>{release.id}</code>
        </div>
      </div>
      <dl className="release-facts">
        <div>
          <dt>PREDECESSOR</dt>
          <dd>{release.predecessor_id ?? "ROOT"}</dd>
        </div>
        <div>
          <dt>RESEARCH RANGE</dt>
          <dd>
            {release.appended_session_range.start} → {release.appended_session_range.end}
          </dd>
        </div>
        <div>
          <dt>COVERAGE</dt>
          <dd>
            {release.session_count} sessions · {release.instrument_count} instruments
          </dd>
        </div>
        <div>
          <dt>OBJECTS</dt>
          <dd>{release.objects.length} immutable objects</dd>
        </div>
      </dl>
      <div className="manifest-line">
        <span>MANIFEST</span>
        <code>{release.manifest_sha256.slice(0, 24)}…</code>
      </div>
    </div>
  );
}

function HealthRow({ label, health }: { label: string; health: ComponentHealth }) {
  return (
    <div className="health-row">
      <div>
        <span className={`health-dot ${health.status}`} />
        <strong>{label}</strong>
      </div>
      <span className={`health-label ${health.status}`}>
        {health.status === "available" ? "AVAILABLE" : "UNAVAILABLE"}
      </span>
    </div>
  );
}

function StatusPanel({
  message,
  detail,
  tone = "loading",
}: {
  message: string;
  detail?: string;
  tone?: "loading" | "error";
}) {
  return (
    <section className={`status-panel ${tone}`}>
      <Activity size={24} aria-hidden="true" />
      <div>
        <h2>{message}</h2>
        {detail && <p>{detail}</p>}
      </div>
    </section>
  );
}

function assertResponse(response: Response): Response {
  if (!response.ok) {
    throw new Error(`Workspace request failed with ${response.status}`);
  }
  return response;
}
