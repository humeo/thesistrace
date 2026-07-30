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
  latest_dataset_release: string | null;
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
                    </div>
                  </div>
                ) : (
                  <p>{state.workspace.latest_dataset_release}</p>
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
