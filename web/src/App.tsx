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
import { useEffect, useRef, useState } from "react";

import "./app.css";
import { apiFetch } from "./hostedAuth";

const fetch = apiFetch;

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
  schemas: { family: string; version: string }[];
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
  fields: {
    name: string;
    field_id: string;
    definition: string;
    unit: string;
    time_semantics: string;
    alpha_authorable: boolean;
    coverage: string;
    release_available_from: string;
  }[];
  alpha_authorable_fields: string[];
  universes: string[];
  industry_levels: string[];
  trading_state_counts: Record<string, number>;
};

type WorkspaceState =
  | { status: "loading" }
  | { status: "ready"; workspace: Workspace; health: Health }
  | { status: "error" };

type RunStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

type ResearchResult = {
  manifest: {
    id: string;
    research_run_id: string;
    dataset_release: { id: string };
    definition: { id: string; content_hash: string };
    calculation_kernel: string;
    objects: Record<string, { kind: string; sha256: string; bytes: number }>;
  };
  factor_evaluation: {
    horizons: Record<
      string,
      {
        summary: {
          ic: FactorCorrelationSummary;
          rank_ic: FactorCorrelationSummary;
          quantile_returns: Record<string, number | null>;
          top_bottom_return: number | null;
        };
        diagnostics: {
          session_count: number;
          missing_session_count: number;
          correlation_reason_counts: Record<string, number>;
          quantile_reason_counts: Record<string, number>;
        };
      }
    >;
  };
  strategy_backtest: {
    daily: {
      session: string;
      net_nav: string;
      benchmark_nav: string;
      holdings_count: number;
      maximum_single_name_weight: number;
      cash_ratio: number;
    }[];
    metrics: {
      gross_cumulative_return: number;
      net_cumulative_return: number;
      net_cagr: number | null;
      gross_cagr: number | null;
      benchmark_cumulative_return: number;
      benchmark_cagr: number | null;
      annualized_excess_return: number | null;
      maximum_drawdown: {
        value: number;
        series: { session: string; drawdown: number }[];
      };
      annualized_volatility: number | null;
      sharpe: number | null;
      calmar: number | null;
      turnover: {
        average_rebalance: number | null;
        annualized: number | null;
        events: { session: string; value: number }[];
      };
      transaction_costs: {
        cumulative_amount: number;
        ratio: number;
        return_drag: number;
      };
      holdings_count: {
        mean: number;
        minimum: number;
        maximum: number;
        ending: number;
      };
      maximum_single_name_weight: {
        period_maximum: { value: number; session: string };
        ending: number;
      };
      cash_ratio: {
        mean: number;
        maximum: { value: number; session: string };
        ending: number;
      };
      market_rejections: Record<string, number>;
    };
  };
  diagnostics: {
    alpha_coverage_summary: {
      session_count: number;
      loss_session_count: number;
      reason_counts: Record<string, number>;
    };
    strategy_summary: {
      event_count: number;
      reason_counts: Record<string, number>;
    };
  };
};

type FactorCorrelationSummary = {
  mean: number | null;
  sample_deviation: number | null;
  icir: number | null;
  positive_fraction: number | null;
  valid_session_count: number;
};

const resources = [
  { key: "dataset_releases", label: "Dataset Releases", icon: Database },
  { key: "research_definitions", label: "Research Definitions", icon: FlaskConical },
  { key: "research_runs", label: "Research Runs", icon: Activity },
  { key: "daily_tracks", label: "Daily Tracks", icon: Radio },
] as const;

export default function App() {
  const workspaceEpoch = useRef(0);
  const [state, setState] = useState<WorkspaceState>({ status: "loading" });
  const [publication, setPublication] = useState<"idle" | "running" | "failed">("idle");
  const [publicationError, setPublicationError] = useState<string | null>(null);
  const [liveAsOf, setLiveAsOf] = useState(new Date().toISOString().slice(0, 10));

  useEffect(() => {
    const controller = new AbortController();
    let loaded = false;
    let timeout: number | undefined;

    async function refreshWorkspace() {
      const epoch = workspaceEpoch.current;
      try {
        const [workspaceResponse, healthResponse] = await Promise.all([
          fetch("/api/v1/workspace", { signal: controller.signal }).then(assertResponse),
          fetch("/api/v1/health", { signal: controller.signal }).then(assertResponse),
        ]);
        const [workspace, health] = await Promise.all([
          workspaceResponse.json() as Promise<Workspace>,
          healthResponse.json() as Promise<Health>,
        ]);
        if (epoch === workspaceEpoch.current) {
          loaded = true;
          setState({ status: "ready", workspace, health });
        }
      } catch (error: unknown) {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          if (!loaded && epoch === workspaceEpoch.current) {
            setState({ status: "error" });
          }
        }
      } finally {
        if (!controller.signal.aborted) {
          timeout = window.setTimeout(() => void refreshWorkspace(), 2_000);
        }
      }
    }

    void refreshWorkspace();
    return () => {
      if (timeout !== undefined) {
        window.clearTimeout(timeout);
      }
      controller.abort();
    };
  }, []);

  async function bootstrapFixture() {
    if (state.status !== "ready") {
      return;
    }
    workspaceEpoch.current += 1;
    setPublication("running");
    setPublicationError(null);
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
      workspaceEpoch.current += 1;
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
    } catch (error: unknown) {
      workspaceEpoch.current += 1;
      setPublication("failed");
      setPublicationError(
        apiErrorMessage(error, "PUBLICATION_FAILED · Fixture Bootstrap 发布失败"),
      );
    }
  }

  async function bootstrapLive() {
    if (state.status !== "ready") {
      return;
    }
    workspaceEpoch.current += 1;
    setPublication("running");
    setPublicationError(null);
    try {
      const response = await fetch("/api/v1/dataset-releases/bootstrap-live", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": crypto.randomUUID(),
        },
        body: JSON.stringify({ as_of: liveAsOf }),
      }).then(assertResponse);
      const payload = (await response.json()) as { release: DatasetRelease };
      workspaceEpoch.current += 1;
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
    } catch (error: unknown) {
      workspaceEpoch.current += 1;
      setPublication("failed");
      setPublicationError(
        apiErrorMessage(error, "PUBLICATION_FAILED · Live Bootstrap 发布失败"),
      );
    }
  }

  async function publishFixtureSession() {
    if (state.status !== "ready") {
      return;
    }
    workspaceEpoch.current += 1;
    setPublication("running");
    setPublicationError(null);
    try {
      const response = await fetch("/api/v1/dataset-releases/publish-fixture", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": crypto.randomUUID(),
        },
        body: JSON.stringify({ new_sessions: 1, corrections: [] }),
      }).then(assertResponse);
      const payload = (await response.json()) as { release: DatasetRelease };
      workspaceEpoch.current += 1;
      setState({
        status: "ready",
        health: state.health,
        workspace: {
          ...state.workspace,
          latest_dataset_release: payload.release,
          resource_counts: {
            ...state.workspace.resource_counts,
            dataset_releases: state.workspace.resource_counts.dataset_releases + 1,
          },
        },
      });
      setPublication("idle");
    } catch (error: unknown) {
      workspaceEpoch.current += 1;
      setPublication("failed");
      setPublicationError(
        apiErrorMessage(error, "PUBLICATION_FAILED · Fixture Session 发布失败"),
      );
    }
  }

  async function publishLiveSession() {
    if (state.status !== "ready") {
      return;
    }
    workspaceEpoch.current += 1;
    setPublication("running");
    setPublicationError(null);
    try {
      const response = await fetch("/api/v1/dataset-releases/publish-live", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": crypto.randomUUID(),
        },
        body: JSON.stringify({ as_of: liveAsOf }),
      }).then(assertResponse);
      const payload = (await response.json()) as { release: DatasetRelease };
      workspaceEpoch.current += 1;
      setState({
        status: "ready",
        health: state.health,
        workspace: {
          ...state.workspace,
          latest_dataset_release: payload.release,
          resource_counts: {
            ...state.workspace.resource_counts,
            dataset_releases: state.workspace.resource_counts.dataset_releases + 1,
          },
        },
      });
      setPublication("idle");
    } catch (error: unknown) {
      workspaceEpoch.current += 1;
      setPublication("failed");
      setPublicationError(
        apiErrorMessage(error, "PUBLICATION_FAILED · Live Session 发布失败"),
      );
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
        <a className="rail-link" href="#data">
          <Database size={17} aria-hidden="true" />
          数据
        </a>
        <a className="rail-link" href="#definitions">
          <FlaskConical size={17} aria-hidden="true" />
          研究
        </a>
        <a className="rail-link" href="#operations">
          <Activity size={17} aria-hidden="true" />
          运行记录
        </a>
        <a className="rail-link" href="#tracking">
          <Radio size={17} aria-hidden="true" />
          每日追踪
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
              <section className="release-panel" id="data">
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
                      <label className="live-publication-date">
                        <span>LIVE AS OF</span>
                        <input
                          aria-label="Live 发布截止日期"
                          type="date"
                          value={liveAsOf}
                          onChange={(event) => setLiveAsOf(event.target.value)}
                        />
                      </label>
                      <button
                        className="secondary-button"
                        type="button"
                        onClick={bootstrapLive}
                        disabled={publication === "running"}
                      >
                        发布 Live Tushare Bootstrap
                      </button>
                      {publication === "failed" && publicationError && (
                        <p className="publication-error" role="alert">
                          {publicationError}
                        </p>
                      )}
                    </div>
                  </div>
                ) : (
                  <ReleaseSummary
                    release={state.workspace.latest_dataset_release}
                    publication={publication}
                    publicationError={publicationError}
                    liveAsOf={liveAsOf}
                    onLiveAsOfChange={setLiveAsOf}
                    onPublishFixtureSession={publishFixtureSession}
                    onPublishLiveSession={publishLiveSession}
                  />
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
              <>
                <DataContractPanel releaseId={state.workspace.latest_dataset_release.id} />
                <ResearchDefinitionEditor />
                <OperationsLedger />
              </>
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

type DefinitionForm = {
  title: string;
  hypothesis: string;
  universe: string;
  expression: string;
  neutralization: string;
  holdingsCount: number;
  rebalanceInterval: number;
};

const initialDefinition: DefinitionForm = {
  title: "20 日价格动量",
  hypothesis: "",
  universe: "top300",
  expression: "pct_change($close_adj, 20)",
  neutralization: "industry",
  holdingsCount: 30,
  rebalanceInterval: 5,
};

function ResearchDefinitionEditor() {
  const mutationInFlight = useRef(false);
  const [form, setForm] = useState<DefinitionForm>(initialDefinition);
  const [draftId, setDraftId] = useState<string | null>(null);
  const [status, setStatus] = useState<
    "idle" | "saving" | "saved" | "running" | RunStatus | "error"
  >("idle");
  const [frozenVersion, setFrozenVersion] = useState<number | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [result, setResult] = useState<ResearchResult | null>(null);

  useEffect(() => {
    void restoreLatestRun();
  }, []);

  function content() {
    return {
      title: form.title,
      hypothesis: form.hypothesis,
      dataset_release: "latest",
      universe: form.universe,
      alpha: { expression: form.expression },
      neutralization: form.neutralization,
      strategy: {
        holdings_count: form.holdingsCount,
        rebalance_interval: form.rebalanceInterval,
        initial_cash_cny: "10000000",
        execution: "next_open_full_fill",
      },
      costs: {
        commission_rate_all_in: "0.0003",
        commission_min_cny: "5",
        stamp_duty_sell_rate: "0.0005",
        transfer_fee_rate: "0.00001",
      },
      risk_free_rate: "0",
    };
  }

  async function saveDraft(): Promise<string> {
    setStatus("saving");
    setErrors([]);
    const response = await fetch(
      draftId ? `/api/v1/research-definitions/${draftId}` : "/api/v1/research-definitions",
      {
        method: draftId ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(content()),
      },
    ).then(assertResponse);
    const draft = (await response.json()) as { id: string };
    setDraftId(draft.id);
    setStatus("saved");
    return draft.id;
  }

  async function handleSave() {
    if (mutationInFlight.current) {
      return;
    }
    mutationInFlight.current = true;
    try {
      await saveDraft();
    } catch (error: unknown) {
      setStatus("error");
      setErrors([apiErrorMessage(error, "DRAFT_SAVE_FAILED · Draft 保存失败")]);
    } finally {
      mutationInFlight.current = false;
    }
  }

  async function handleRun() {
    if (mutationInFlight.current) {
      return;
    }
    mutationInFlight.current = true;
    try {
      const currentDraftId = await saveDraft();
      setStatus("running");
      setErrors([]);
      const response = await fetch(`/api/v1/research-definitions/${currentDraftId}/runs`, {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
      });
      if (!response.ok) {
        const payload = (await response.json()) as {
          detail?: {
            reason_code?: string;
            message?: string;
            errors?: {
              location: string;
              reason_code: string;
              message: string;
            }[];
          };
        };
        setErrors(
          payload.detail?.errors?.map(
            (item) =>
              `${item.reason_code} · ${item.location}: ${item.message}`,
          ) ?? [
            payload.detail?.reason_code
              ? `${payload.detail.reason_code} · ${payload.detail.message ?? "研究定义验证失败"}`
              : "DEFINITION_VALIDATION_FAILED · 研究定义验证失败",
          ],
        );
        setStatus("error");
        return;
      }
      const payload = (await response.json()) as {
        frozen_definition: { version: number };
        run: { id: string; status: RunStatus };
      };
      setFrozenVersion(payload.frozen_definition.version);
      setStatus("queued");
      setResult(null);
      await waitForRun(payload.run.id);
    } catch (error: unknown) {
      setStatus("error");
      setErrors([
        apiErrorMessage(error, "RUN_REQUEST_FAILED · ResearchRun 创建失败"),
      ]);
    } finally {
      mutationInFlight.current = false;
    }
  }

  async function waitForRun(runId: string) {
    for (;;) {
      await delay(500);
      const runResponse = await fetch(`/api/v1/research-runs/${runId}`).then(
        assertResponse,
      );
      const run = (await runResponse.json()) as {
        status: RunStatus;
        attempts: {
          diagnostic: { reason_code?: string; message?: string } | null;
        }[];
      };
      setStatus(run.status);
      if (run.status === "succeeded") {
        const resultResponse = await fetch(
          `/api/v1/research-runs/${runId}/result`,
        ).then(assertResponse);
        setResult((await resultResponse.json()) as ResearchResult);
        return;
      }
      if (run.status === "failed" || run.status === "cancelled") {
        const diagnostic = run.attempts.at(-1)?.diagnostic;
        setErrors([
          diagnostic
            ? `${diagnostic.reason_code ?? "RUN_FAILED"} · ${diagnostic.message}`
            : `RUN_${run.status.toUpperCase()} · ResearchRun ${run.status}`,
        ]);
        return;
      }
    }
  }

  async function restoreLatestRun() {
    try {
      const response = await fetch("/api/v1/research-runs").then(assertResponse);
      const payload = (await response.json()) as {
        items: {
          id: string;
          definition_version_id: string;
          status: RunStatus;
          attempts: {
            diagnostic: { reason_code?: string; message?: string } | null;
          }[];
        }[];
      };
      const run = payload.items.at(-1);
      if (!run) {
        return;
      }
      const frozenResponse = await fetch(
        `/api/v1/research-definition-versions/${run.definition_version_id}`,
      ).then(assertResponse);
      const frozen = (await frozenResponse.json()) as { version: number };
      setFrozenVersion(frozen.version);
      setStatus(run.status);
      if (run.status === "succeeded") {
        const resultResponse = await fetch(
          `/api/v1/research-runs/${run.id}/result`,
        ).then(assertResponse);
        setResult((await resultResponse.json()) as ResearchResult);
      } else if (run.status === "queued" || run.status === "running") {
        await waitForRun(run.id);
      } else {
        const diagnostic = run.attempts.at(-1)?.diagnostic;
        setErrors([
          diagnostic
            ? `${diagnostic.reason_code ?? "RUN_FAILED"} · ${diagnostic.message}`
            : `RUN_${run.status.toUpperCase()} · ResearchRun ${run.status}`,
        ]);
      }
    } catch (error: unknown) {
      setErrors([
        apiErrorMessage(
          error,
          "RUN_STATUS_UNAVAILABLE · 最近一次 ResearchRun 状态读取失败",
        ),
      ]);
    }
  }

  return (
    <section className="definition-panel" id="definitions">
      <div className="section-heading">
        <div>
          <p className="eyebrow">AUTHORING / ONE STRUCTURED INPUT</p>
          <h2>Research Definition</h2>
        </div>
        <span className="draft-state">{definitionStatusLabel(status)}</span>
      </div>
      <div className="definition-grid">
        <label className="form-field title-field">
          <span>研究名称</span>
          <input
            value={form.title}
            onChange={(event) => setForm({ ...form, title: event.target.value })}
          />
        </label>
        <label className="form-field hypothesis-field">
          <span>研究假设</span>
          <textarea
            value={form.hypothesis}
            onChange={(event) => setForm({ ...form, hypothesis: event.target.value })}
            placeholder="用一句可验证的话描述 Alpha 假设"
          />
        </label>
        <label className="form-field expression-field">
          <span>Alpha Expression</span>
          <input
            className="code-input"
            value={form.expression}
            onChange={(event) => setForm({ ...form, expression: event.target.value })}
          />
        </label>
        <label className="form-field">
          <span>Liquidity Universe</span>
          <select
            value={form.universe}
            onChange={(event) => setForm({ ...form, universe: event.target.value })}
          >
            <option value="top300">Top 300</option>
            <option value="top1000">Top 1000</option>
            <option value="top2000">Top 2000</option>
            <option value="top3000">Top 3000</option>
          </select>
        </label>
        <label className="form-field">
          <span>Neutralization</span>
          <select
            value={form.neutralization}
            onChange={(event) => setForm({ ...form, neutralization: event.target.value })}
          >
            <option value="none">None</option>
            <option value="industry">Industry demean</option>
          </select>
        </label>
        <label className="form-field">
          <span>Holdings Count</span>
          <input
            type="number"
            min="1"
            max="100"
            value={form.holdingsCount}
            onChange={(event) =>
              setForm({ ...form, holdingsCount: Number(event.target.value) })
            }
          />
        </label>
        <label className="form-field">
          <span>Rebalance Interval</span>
          <input
            type="number"
            min="1"
            max="20"
            value={form.rebalanceInterval}
            onChange={(event) =>
              setForm({ ...form, rebalanceInterval: Number(event.target.value) })
            }
          />
        </label>
        <div className="fixed-contract">
          <span>FIXED V1 CONTRACT</span>
          <strong>CNY 10,000,000 · NEXT OPEN · RF 0%</strong>
          <small>commission 0.03% · min CNY 5 · stamp 0.05% · transfer 0.001%</small>
        </div>
      </div>
      {errors.length > 0 && (
        <ul className="definition-errors" aria-label="验证错误">
          {errors.map((message) => (
            <li key={message}>{message}</li>
          ))}
        </ul>
      )}
      <div className="definition-actions">
        <span>
          {frozenVersion ? `FROZEN VERSION ${frozenVersion}` : "Run 时自动冻结当前 Draft"}
        </span>
        <button
          type="button"
          className="secondary-button"
          onClick={handleSave}
          disabled={
            status === "saving" || status === "queued" || status === "running"
          }
        >
          保存 Draft
        </button>
        <button
          type="button"
          className="bootstrap-button"
          onClick={handleRun}
          disabled={
            status === "saving" || status === "queued" || status === "running"
          }
        >
          运行研究
          <ArrowUpRight size={16} aria-hidden="true" />
        </button>
      </div>
      {result && <ResearchResultPanel result={result} />}
    </section>
  );
}

function ResearchResultPanel({ result }: { result: ResearchResult }) {
  const trackingEpoch = useRef(0);
  const metrics = result.strategy_backtest.metrics;
  const alphaCoverageLossDays =
    result.diagnostics.alpha_coverage_summary.loss_session_count;
  const factorMissingDays = Object.values(
    result.factor_evaluation.horizons,
  ).reduce(
    (total, horizon) => total + horizon.diagnostics.missing_session_count,
    0,
  );
  const [track, setTrack] = useState<{
    id: string;
    status: "active" | "stopped";
    current_generation_id: string;
    head: { target_dataset_release_id: string };
    advances: {
      status: string;
      correction_boundary: {
        target_dataset_release_id: string;
        accepted_correction_change_set: unknown[];
      } | null;
    }[];
  } | null>(null);
  const [trackingError, setTrackingError] = useState<string | null>(null);
  const [trackingView, setTrackingView] = useState<{
    checkpoint: {
      id: string;
      kind: string;
      processed_session_count: number;
      correction_boundary?: {
        target_dataset_release_id: string;
        accepted_correction_change_set: unknown[];
      } | null;
    };
    factor_summary: {
      horizons: Record<
        string,
        { summary: { rank_ic: { mean: number | null } } }
      >;
    };
    strategy: {
      daily: {
        net_nav: string;
        net_cash: string;
        holdings_count: number;
        session: string;
      }[];
    };
    recent_label_maturation: { events: { horizon: number }[] };
  } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let timeout: number | undefined;
    async function refreshTrack() {
      const epoch = trackingEpoch.current;
      try {
        const response = await fetch("/api/v1/daily-tracks", {
          signal: controller.signal,
        }).then(assertResponse);
        const payload = (await response.json()) as {
          items: ({
            seed_run_id: string;
          } & NonNullable<typeof track>)[];
        };
        if (epoch === trackingEpoch.current) {
          setTrack(
            payload.items.find(
              (item) => item.seed_run_id === result.manifest.research_run_id,
            ) ?? null,
          );
          setTrackingError(null);
        }
      } catch (error: unknown) {
        if (
          !(error instanceof DOMException && error.name === "AbortError") &&
          epoch === trackingEpoch.current
        ) {
          setTrackingError(
            apiErrorMessage(
              error,
              "TRACK_STATUS_UNAVAILABLE · 追踪状态读取失败",
            ),
          );
        }
      } finally {
        if (!controller.signal.aborted) {
          timeout = window.setTimeout(() => void refreshTrack(), 2_000);
        }
      }
    }
    void refreshTrack();
    return () => {
      if (timeout !== undefined) {
        window.clearTimeout(timeout);
      }
      controller.abort();
    };
  }, [result.manifest.research_run_id]);

  useEffect(() => {
    if (!track) {
      setTrackingView(null);
      return;
    }
    const controller = new AbortController();
    let timeout: number | undefined;
    async function refreshCurrent() {
      const epoch = trackingEpoch.current;
      try {
        const response = await fetch(
          `/api/v1/daily-tracks/${track?.id}/current`,
          { signal: controller.signal },
        ).then(assertResponse);
        const view = await response.json();
        if (epoch === trackingEpoch.current) {
          setTrackingView(view);
          setTrackingError(null);
        }
      } catch (error: unknown) {
        if (
          !(error instanceof DOMException && error.name === "AbortError") &&
          epoch === trackingEpoch.current
        ) {
          setTrackingError(
            apiErrorMessage(error, "TRACK_VIEW_UNAVAILABLE · 追踪详情读取失败"),
          );
        }
      } finally {
        if (!controller.signal.aborted) {
          timeout = window.setTimeout(() => void refreshCurrent(), 2_000);
        }
      }
    }
    void refreshCurrent();
    return () => {
      if (timeout !== undefined) {
        window.clearTimeout(timeout);
      }
      controller.abort();
    };
  }, [track?.id]);

  async function activateTracking() {
    trackingEpoch.current += 1;
    try {
      const response = await fetch(
        `/api/v1/research-runs/${result.manifest.research_run_id}/daily-tracks`,
        {
          method: "POST",
          headers: {
            "Idempotency-Key": `daily-track-${result.manifest.research_run_id}`,
          },
        },
      ).then(assertResponse);
      const activated = await response.json();
      trackingEpoch.current += 1;
      setTrack(activated);
      setTrackingError(null);
    } catch (error: unknown) {
      trackingEpoch.current += 1;
      setTrackingError(
        apiErrorMessage(error, "TRACK_ACTIVATION_FAILED · 每日追踪启动失败"),
      );
    }
  }

  async function stopTracking() {
    if (!track) {
      return;
    }
    trackingEpoch.current += 1;
    try {
      const response = await fetch(`/api/v1/daily-tracks/${track.id}/stop`, {
        method: "POST",
      }).then(assertResponse);
      const stopped = await response.json();
      trackingEpoch.current += 1;
      setTrack(stopped);
      setTrackingError(null);
    } catch (error: unknown) {
      trackingEpoch.current += 1;
      setTrackingError(
        apiErrorMessage(error, "TRACK_STOP_FAILED · 每日追踪停止失败"),
      );
    }
  }

  return (
    <section className="result-panel" id="runs" aria-label="ResearchRun 结果">
      <div className="result-provenance">
        <div>
          <span>RESULT BUNDLE</span>
          <code>{result.manifest.id}</code>
        </div>
        <div>
          <span>DATASET RELEASE</span>
          <code>{result.manifest.dataset_release.id}</code>
        </div>
        <div>
          <span>FROZEN DEFINITION</span>
          <code>{result.manifest.definition.id}</code>
        </div>
        <div>
          <span>KERNEL</span>
          <code>{result.manifest.calculation_kernel}</code>
        </div>
      </div>
      <div className="result-columns">
        <div className="result-conclusion">
          <p className="eyebrow">FACTOR EVALUATION</p>
          <h3>因子结论</h3>
          <div className="factor-horizons">
            {["1", "5", "20"].map((horizon) => {
              const summary = result.factor_evaluation.horizons[horizon].summary;
              return (
                <div key={horizon}>
                  <strong>{horizon}D</strong>
                  <Metric label="IC MEAN" value={formatNumber(summary.ic.mean)} />
                  <Metric
                    label="RANK IC"
                    value={formatNumber(summary.rank_ic.mean)}
                  />
                  <Metric
                    label="TOP−BOTTOM"
                    value={formatPercent(summary.top_bottom_return)}
                  />
                  <Metric label="ICIR" value={formatNumber(summary.ic.icir)} />
                  <Metric
                    label="RANK ICIR"
                    value={formatNumber(summary.rank_ic.icir)}
                  />
                  <Metric
                    label="POSITIVE RANK IC"
                    value={formatPercent(summary.rank_ic.positive_fraction)}
                  />
                  <Metric
                    label="VALID SESSIONS"
                    value={String(summary.rank_ic.valid_session_count)}
                  />
                  <table className="quantile-table">
                    <thead>
                      <tr>
                        {["q1", "q2", "q3", "q4", "q5"].map((quantile) => (
                          <th key={quantile}>{quantile.toUpperCase()}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        {["q1", "q2", "q3", "q4", "q5"].map((quantile) => (
                          <td key={quantile}>
                            {formatPercent(summary.quantile_returns[quantile])}
                          </td>
                        ))}
                      </tr>
                    </tbody>
                  </table>
                </div>
              );
            })}
          </div>
        </div>
        <div className="result-conclusion">
          <p className="eyebrow">STRATEGY BACKTEST</p>
          <h3>策略结论</h3>
          <div className="strategy-metrics">
            <Metric
              label="NET RETURN"
              value={formatPercent(metrics.net_cumulative_return)}
            />
            <Metric label="NET CAGR" value={formatPercent(metrics.net_cagr)} />
            <Metric
              label="BENCHMARK"
              value={formatPercent(metrics.benchmark_cumulative_return)}
            />
            <Metric
              label="MAX DRAWDOWN"
              value={formatPercent(metrics.maximum_drawdown.value)}
            />
            <Metric label="SHARPE" value={formatNumber(metrics.sharpe)} />
            <Metric
              label="COST CNY"
              value={metrics.transaction_costs.cumulative_amount.toFixed(2)}
            />
          </div>
        </div>
      </div>
      <div className="result-evidence">
        <div>
          <span>NET NAV</span>
          <Sparkline
            values={result.strategy_backtest.daily.map((item) =>
              Number(item.net_nav),
            )}
            label="策略 Net NAV 日序列"
          />
        </div>
        <div>
          <span>BENCHMARK NAV</span>
          <Sparkline
            values={result.strategy_backtest.daily.map((item) =>
              Number(item.benchmark_nav),
            )}
            label="基准 NAV 日序列"
          />
        </div>
        <div>
          <span>DRAWDOWN</span>
          <Sparkline
            values={metrics.maximum_drawdown.series.map((item) => item.drawdown)}
            label="策略回撤日序列"
          />
        </div>
        <div>
          <span>TURNOVER</span>
          <Sparkline
            values={metrics.turnover.events.map((item) => item.value)}
            label="调仓换手率序列"
          />
        </div>
        <div>
          <span>HOLDINGS</span>
          <Sparkline
            values={result.strategy_backtest.daily.map(
              (item) => item.holdings_count,
            )}
            label="实际持仓数量日序列"
          />
        </div>
        <div>
          <span>MAX NAME WEIGHT</span>
          <Sparkline
            values={result.strategy_backtest.daily.map(
              (item) => item.maximum_single_name_weight,
            )}
            label="最大单股权重日序列"
          />
        </div>
        <div>
          <span>CASH RATIO</span>
          <Sparkline
            values={result.strategy_backtest.daily.map((item) => item.cash_ratio)}
            label="现金比例日序列"
          />
        </div>
      </div>
      <div className="metric-register">
        <Metric
          label="GROSS RETURN"
          value={formatPercent(metrics.gross_cumulative_return)}
        />
        <Metric label="GROSS CAGR" value={formatPercent(metrics.gross_cagr)} />
        <Metric
          label="EXCESS CAGR"
          value={formatPercent(metrics.annualized_excess_return)}
        />
        <Metric
          label="BENCHMARK CAGR"
          value={formatPercent(metrics.benchmark_cagr)}
        />
        <Metric
          label="VOLATILITY"
          value={formatPercent(metrics.annualized_volatility)}
        />
        <Metric label="CALMAR" value={formatNumber(metrics.calmar)} />
        <Metric
          label="TURNOVER"
          value={formatPercent(metrics.turnover.annualized)}
        />
        <Metric
          label="AVG REBALANCE"
          value={formatPercent(metrics.turnover.average_rebalance)}
        />
        <Metric
          label="COST RATIO"
          value={formatPercent(metrics.transaction_costs.ratio)}
        />
        <Metric
          label="RETURN DRAG"
          value={formatPercent(metrics.transaction_costs.return_drag)}
        />
        <Metric
          label="HOLDINGS MEAN / RANGE / END"
          value={`${metrics.holdings_count.mean.toFixed(1)} / ${metrics.holdings_count.minimum}–${metrics.holdings_count.maximum} / ${metrics.holdings_count.ending}`}
        />
        <Metric
          label="MAX NAME WEIGHT"
          value={formatPercent(
            metrics.maximum_single_name_weight.period_maximum.value,
          )}
        />
        <Metric
          label="CASH / END"
          value={formatPercent(metrics.cash_ratio.ending)}
        />
        <Metric
          label="CASH MEAN / MAX"
          value={`${formatPercent(metrics.cash_ratio.mean)} / ${formatPercent(
            metrics.cash_ratio.maximum.value,
          )}`}
        />
        <Metric
          label="REJECT UP / DOWN / SUSP"
          value={`${metrics.market_rejections.upper_limit_buy ?? 0} / ${
            metrics.market_rejections.lower_limit_sell ?? 0
          } / ${metrics.market_rejections.suspension ?? 0}`}
        />
      </div>
      <div className="diagnostic-register">
        <span>DIAGNOSTICS</span>
        <strong>{alphaCoverageLossDays} Alpha coverage-loss sessions</strong>
        <strong>{factorMissingDays} horizon-session factor diagnostics</strong>
        <strong>
          {result.diagnostics.strategy_summary.event_count} Strategy diagnostics
        </strong>
        <small>
          报告仅保留 bounded reason-count summaries；逐事件计算明细不持久化。
        </small>
      </div>
      <div className="tracking-control" id="tracking">
        <div>
          <span>DAILY TRACKING</span>
          {track ? (
            <>
              <strong>{track.status.toUpperCase()}</strong>
              <code>
                {track.id} · {track.current_generation_id} ·{" "}
                {track.head.target_dataset_release_id}
              </code>
              {trackingView && (
                <small>
                  HEAD {trackingView.checkpoint.id} ·{" "}
                  {trackingView.strategy.daily.at(-1)?.session} · NET NAV{" "}
                  {trackingView.strategy.daily.at(-1)?.net_nav} · RANK IC{" "}
                  {formatNumber(
                    trackingView.factor_summary.horizons["1"]?.summary.rank_ic.mean ??
                      null,
                  )}{" "}
                  · {trackingView.recent_label_maturation.events.length} LABEL EVENTS ·
                  NET CASH {trackingView.strategy.daily.at(-1)?.net_cash} · HOLDINGS{" "}
                  {trackingView.strategy.daily.at(-1)?.holdings_count} · PROCESSED{" "}
                  {trackingView.checkpoint.processed_session_count}
                </small>
              )}
              {trackingView?.recent_label_maturation.events.length ? (
                <small>
                  RECENT MATURITY ·{" "}
                  {trackingView.recent_label_maturation.events
                    .slice(-5)
                    .map((event) => `T+${event.horizon}`)
                    .join(" · ")}
                </small>
              ) : null}
              {trackingView?.checkpoint.correction_boundary ? (
                <small>
                  CORRECTION BOUNDARY ·{" "}
                  {trackingView.checkpoint.correction_boundary.target_dataset_release_id} ·{" "}
                  {
                    trackingView.checkpoint.correction_boundary
                      .accepted_correction_change_set.length
                  }{" "}
                  ACCEPTED CHANGE
                </small>
              ) : null}
            </>
          ) : (
            <>
              <strong>NOT ACTIVATED</strong>
              <small>从本次成功 Result Bundle 延续同一个模拟账户</small>
            </>
          )}
        </div>
        {track?.status === "active" ? (
          <button type="button" className="secondary-button" onClick={stopTracking}>
            停止追踪
          </button>
        ) : track === null ? (
          <button
            type="button"
            className="bootstrap-button"
            onClick={activateTracking}
          >
            开始每日追踪
            <ArrowUpRight size={16} aria-hidden="true" />
          </button>
        ) : null}
        {trackingError && <span className="tracking-error">{trackingError}</span>}
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="result-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function OperationsLedger() {
  const ledgerEpoch = useRef(0);
  const [releases, setReleases] = useState<DatasetRelease[]>([]);
  const [drafts, setDrafts] = useState<
    { id: string; state: string; updated_at: string; content: { title?: string } }[]
  >([]);
  const [frozenDefinitions, setFrozenDefinitions] = useState<
    {
      id: string;
      draft_id: string;
      version: number;
      content_hash: string;
      content: { title?: string };
    }[]
  >([]);
  const [runs, setRuns] = useState<
    {
      id: string;
      status: RunStatus;
      definition_version_id: string;
      dataset_release_id: string;
      result_bundle_id: string | null;
      attempts: {
        ordinal: number;
        status: string;
        diagnostic: { reason_code?: string; message?: string } | null;
      }[];
    }[]
  >([]);
  const [tracks, setTracks] = useState<
    {
      id: string;
      status: string;
      current_generation_id: string;
      head_checkpoint_id: string;
      generations: { id: string; reason: string }[];
      advances: {
        id: string;
        status: string;
        target_dataset_release_id: string;
        correction_boundary: {
          target_dataset_release_id: string;
          accepted_correction_change_set: unknown[];
        } | null;
      }[];
      checkpoints: { id: string; target_dataset_release_id: string }[];
    }[]
  >([]);
  const [loaded, setLoaded] = useState(false);
  const [operationError, setOperationError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let timeout: number | undefined;
    async function poll() {
      await refresh(controller.signal);
      if (!controller.signal.aborted) {
        timeout = window.setTimeout(() => void poll(), 2_000);
      }
    }
    void poll();
    return () => {
      if (timeout !== undefined) {
        window.clearTimeout(timeout);
      }
      controller.abort();
    };
  }, []);

  async function refresh(signal?: AbortSignal) {
    const epoch = ledgerEpoch.current;
    try {
      const [
        releaseResponse,
        draftResponse,
        frozenResponse,
        runResponse,
        trackResponse,
      ] = await Promise.all([
        fetch("/api/v1/dataset-releases", { signal }).then(assertResponse),
        fetch("/api/v1/research-definitions", { signal }).then(assertResponse),
        fetch("/api/v1/research-definition-versions", { signal }).then(assertResponse),
        fetch("/api/v1/research-runs", { signal }).then(assertResponse),
        fetch("/api/v1/daily-tracks", { signal }).then(assertResponse),
      ]);
      const [
        releasePayload,
        draftPayload,
        frozenPayload,
        runPayload,
        trackPayload,
      ] = await Promise.all([
        releaseResponse.json(),
        draftResponse.json(),
        frozenResponse.json(),
        runResponse.json(),
        trackResponse.json(),
      ]);
      if (epoch === ledgerEpoch.current) {
        setReleases(releasePayload.items);
        setDrafts(draftPayload.items);
        setFrozenDefinitions(frozenPayload.items);
        setRuns(runPayload.items);
        setTracks(trackPayload.items);
        setLoaded(true);
        setOperationError(null);
      }
    } catch (error: unknown) {
      if (
        !(error instanceof DOMException && error.name === "AbortError") &&
        epoch === ledgerEpoch.current
      ) {
        setLoaded(true);
        setOperationError(
          apiErrorMessage(
            error,
            "RESOURCE_REFRESH_FAILED · 运行与追踪记录读取失败",
          ),
        );
      }
    }
  }

  async function cancelRun(runId: string) {
    ledgerEpoch.current += 1;
    try {
      await fetch(`/api/v1/research-runs/${runId}/cancel`, {
        method: "POST",
      }).then(assertResponse);
      ledgerEpoch.current += 1;
      await refresh();
    } catch (error: unknown) {
      ledgerEpoch.current += 1;
      setOperationError(
        apiErrorMessage(error, "RUN_CANCEL_FAILED · ResearchRun 取消失败"),
      );
    }
  }

  async function rerun(runId: string) {
    ledgerEpoch.current += 1;
    try {
      await fetch(`/api/v1/research-runs/${runId}/rerun`, {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
      }).then(assertResponse);
      ledgerEpoch.current += 1;
      await refresh();
    } catch (error: unknown) {
      ledgerEpoch.current += 1;
      setOperationError(
        apiErrorMessage(error, "RUN_RERUN_FAILED · ResearchRun 重新运行失败"),
      );
    }
  }

  async function deleteResource(
    resourceKind: "research-runs" | "daily-tracks",
    resourceId: string,
  ) {
    const noun = resourceKind === "research-runs" ? "ResearchRun" : "DailyTrack";
    if (!window.confirm(`永久删除 ${noun} ${resourceId}？此操作无法恢复。`)) {
      return;
    }
    ledgerEpoch.current += 1;
    try {
      await fetch(`/api/v1/${resourceKind}/${resourceId}`, {
        method: "DELETE",
      }).then(assertResponse);
      ledgerEpoch.current += 1;
      await refresh();
    } catch (error: unknown) {
      ledgerEpoch.current += 1;
      setOperationError(
        apiErrorMessage(error, `RESOURCE_DELETE_FAILED · ${noun} 删除失败`),
      );
    }
  }

  return (
    <section className="operations-panel" id="operations">
      <div className="section-heading">
        <div>
          <p className="eyebrow">DURABLE RESOURCE HISTORY</p>
          <h2>运行与追踪记录</h2>
        </div>
        <span className="contract-version">IMMUTABLE LEDGER</span>
      </div>
      {operationError && (
        <p className="ledger-diagnostic" role="alert">
          {operationError}
        </p>
      )}
      {!loaded ? (
        <p className="ledger-empty">正在读取 Runs 与 DailyTracks…</p>
      ) : releases.length === 0 &&
        drafts.length === 0 &&
        frozenDefinitions.length === 0 &&
        runs.length === 0 &&
        tracks.length === 0 ? (
        <p className="ledger-empty">
          尚无运行记录。保存 Draft 并运行后，这里会展示 frozen Definition、Attempt 和
          Result Bundle。
        </p>
      ) : (
        <>
          <div className="ledger-columns resource-ledger">
            <div>
              <span className="ledger-title">DATASET RELEASES</span>
              {releases.map((release) => (
                <article className="ledger-row" key={release.id}>
                  <div>
                    <strong>
                      <a
                        className="resource-link"
                        href={`/api/v1/dataset-releases/${release.id}`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {release.id}
                      </a>
                    </strong>
                    <span className="ledger-status succeeded">published</span>
                  </div>
                  <code>
                    {release.predecessor_id ?? "ROOT"} · {release.session_count} sessions
                  </code>
                  <small>
                    {release.objects.length} objects · manifest{" "}
                    {release.manifest_sha256.slice(0, 12)}
                  </small>
                </article>
              ))}
            </div>
            <div>
              <span className="ledger-title">DEFINITIONS</span>
              {drafts.map((draft) => (
                <article className="ledger-row" key={draft.id}>
                  <div>
                    <strong>{draft.content.title ?? draft.id}</strong>
                    <span className="ledger-status">{draft.state}</span>
                  </div>
                  <code>{draft.id}</code>
                  <a
                    className="resource-link resource-inspect-link"
                    href={`/api/v1/research-definitions/${draft.id}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    查看 Draft
                  </a>
                </article>
              ))}
              {frozenDefinitions.map((definition) => (
                <article className="ledger-row" key={definition.id}>
                  <div>
                    <strong>
                      {definition.content.title ?? definition.id} · v
                      {definition.version}
                    </strong>
                    <span className="ledger-status succeeded">frozen</span>
                  </div>
                  <code>
                    {definition.id} · {definition.content_hash.slice(0, 12)}
                  </code>
                  <small>source Draft {definition.draft_id}</small>
                  <a
                    className="resource-link resource-inspect-link"
                    href={`/api/v1/research-definition-versions/${definition.id}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    查看 Frozen Version
                  </a>
                </article>
              ))}
            </div>
          </div>
          <div className="ledger-columns">
          <div>
            <span className="ledger-title">RESEARCH RUNS</span>
            {runs.map((run) => {
              const latestAttempt = run.attempts.at(-1);
              return (
                <article className="ledger-row" key={run.id}>
                  <div>
                    <strong>
                      <a
                        className="resource-link"
                        href={`/api/v1/research-runs/${run.id}`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {run.id}
                      </a>
                    </strong>
                    <span className={`ledger-status ${run.status}`}>
                      {run.status}
                    </span>
                  </div>
                  <code>
                    {run.definition_version_id} · {run.dataset_release_id}
                  </code>
                  <small>
                    {run.result_bundle_id
                      ? (
                          <a
                            className="resource-link"
                            href={`/api/v1/research-runs/${run.id}/result`}
                            target="_blank"
                            rel="noreferrer"
                          >
                            Result Bundle {run.result_bundle_id}
                          </a>
                        )
                      : "Result Bundle pending"}
                  </small>
                  <ol className="attempt-list" aria-label={`${run.id} Attempts`}>
                    {run.attempts.map((attempt) => (
                      <li key={attempt.ordinal}>
                        <a
                          className="resource-link"
                          href={`/api/v1/research-runs/${run.id}/attempts/${attempt.ordinal}`}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Attempt {attempt.ordinal} · {attempt.status}
                        </a>
                      </li>
                    ))}
                  </ol>
                  {latestAttempt?.diagnostic && (
                    <p className="ledger-diagnostic">
                      {latestAttempt.diagnostic.reason_code ?? "DIAGNOSTIC"} ·{" "}
                      {latestAttempt.diagnostic.message}
                    </p>
                  )}
                  <div className="ledger-actions">
                    {(run.status === "queued" || run.status === "running") && (
                      <button
                        type="button"
                        onClick={() => void cancelRun(run.id)}
                      >
                        取消
                      </button>
                    )}
                    {(run.status === "succeeded" ||
                      run.status === "failed" ||
                      run.status === "cancelled") && (
                      <>
                        <button type="button" onClick={() => void rerun(run.id)}>
                          重新运行
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            void deleteResource("research-runs", run.id)
                          }
                        >
                          永久删除
                        </button>
                      </>
                    )}
                  </div>
                </article>
              );
            })}
          </div>
          <div>
            <span className="ledger-title">DAILY TRACKS</span>
            {tracks.map((track) => {
              const blocked = track.advances.filter(
                (advance) => advance.status === "blocked",
              ).length;
              const pending = track.advances.filter(
                (advance) =>
                  advance.status === "pending" || advance.status === "running",
              ).length;
              return (
                <article className="ledger-row" key={track.id}>
                  <div>
                    <strong>
                      <a
                        className="resource-link"
                        href={`/api/v1/daily-tracks/${track.id}`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {track.id}
                      </a>
                    </strong>
                    <span className={`ledger-status ${track.status}`}>
                      {track.status}
                    </span>
                  </div>
                  <code>
                    HEAD {track.head_checkpoint_id} · {track.current_generation_id}
                  </code>
                  <small>
                    {track.generations.length} generation ·{" "}
                    {track.checkpoints.length} checkpoint · lag {pending + blocked} ·
                    blocked {blocked}
                  </small>
                  <ol className="attempt-list" aria-label={`${track.id} resources`}>
                    {track.generations.map((generation) => (
                      <li key={generation.id}>
                        <a
                          className="resource-link"
                          href={`/api/v1/daily-tracks/${track.id}/generations/${generation.id}`}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Generation {generation.id} · {generation.reason}
                        </a>
                      </li>
                    ))}
                    {track.advances.map((advance) => (
                      <li key={advance.id}>
                        <a
                          className="resource-link"
                          href={`/api/v1/daily-tracks/${track.id}/advances/${advance.id}`}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Advance {advance.id} · {advance.status}
                          {advance.correction_boundary
                            ? ` · Correction Boundary ${
                                advance.correction_boundary.target_dataset_release_id
                              } · ${
                                advance.correction_boundary
                                  .accepted_correction_change_set.length
                              } accepted change`
                            : ""}
                        </a>
                      </li>
                    ))}
                    {track.checkpoints.map((checkpoint) => (
                      <li key={checkpoint.id}>
                        <a
                          className="resource-link"
                          href={`/api/v1/daily-tracks/${track.id}/checkpoints/${checkpoint.id}`}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Checkpoint {checkpoint.id}
                        </a>
                      </li>
                    ))}
                  </ol>
                  {blocked > 0 && (
                    <p className="ledger-diagnostic">
                      BLOCKED_FRONTIER · Worker 将在同一 Advance 身份下重试
                    </p>
                  )}
                  {track.status === "stopped" && (
                    <div className="ledger-actions">
                      <button
                        type="button"
                        onClick={() =>
                          void deleteResource("daily-tracks", track.id)
                        }
                      >
                        永久删除
                      </button>
                    </div>
                  )}
                </article>
              );
            })}
          </div>
          </div>
        </>
      )}
    </section>
  );
}

function Sparkline({
  values,
  label,
}: {
  values: (number | null)[];
  label: string;
}) {
  const finite = values.filter(
    (value): value is number => value !== null && Number.isFinite(value),
  );
  if (finite.length < 2) {
    return <div className="chart-empty">INSUFFICIENT DATA</div>;
  }
  const minimum = Math.min(...finite);
  const maximum = Math.max(...finite);
  const spread = maximum - minimum || 1;
  const points = values
    .map((value, index) =>
      value === null || !Number.isFinite(value)
        ? null
        : `${(index / Math.max(1, values.length - 1)) * 100},${
            34 - ((value - minimum) / spread) * 32
          }`,
    )
    .filter((value): value is string => value !== null)
    .join(" ");
  return (
    <svg
      className="sparkline"
      viewBox="0 0 100 36"
      role="img"
      aria-label={label}
      preserveAspectRatio="none"
    >
      <line x1="0" y1="34" x2="100" y2="34" />
      <polyline points={points} />
    </svg>
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
          <span>FIELD CATALOG</span>
          <div className="field-catalog">
            {contract.fields.map((field) => (
              <details key={field.field_id}>
                <summary>
                  <code>{field.name}</code>
                  {field.alpha_authorable ? " · ALPHA" : ""}
                </summary>
                <small>{field.field_id} · {field.unit} · {field.time_semantics}</small>
                <small>{field.definition}</small>
                <small>
                  {field.coverage} · available from {field.release_available_from}
                </small>
              </details>
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

function ReleaseSummary({
  release,
  publication,
  publicationError,
  liveAsOf,
  onLiveAsOfChange,
  onPublishFixtureSession,
  onPublishLiveSession,
}: {
  release: DatasetRelease;
  publication: "idle" | "running" | "failed";
  publicationError: string | null;
  liveAsOf: string;
  onLiveAsOfChange: (value: string) => void;
  onPublishFixtureSession: () => Promise<void>;
  onPublishLiveSession: () => Promise<void>;
}) {
  const liveSource = release.schemas.some(
    (schema) => schema.family === "source_tushare",
  );
  return (
    <div className="release-summary">
      <div className="release-lead">
        <span className="release-status">PUBLISHED</span>
        <div>
          <h3>
            {release.predecessor_id === null
              ? liveSource
                ? "Live Tushare Bootstrap 已发布"
                : "Fixture Bootstrap 已发布"
              : "Dataset Release 已发布"}
          </h3>
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
      <div className="release-actions">
        {liveSource ? (
          <>
            <label className="live-publication-date">
              <span>LIVE AS OF</span>
              <input
                aria-label="Live 发布截止日期"
                type="date"
                value={liveAsOf}
                onChange={(event) => onLiveAsOfChange(event.target.value)}
              />
            </label>
            <button
              type="button"
              className="secondary-button"
              onClick={() => void onPublishLiveSession()}
              disabled={publication === "running"}
            >
              {publication === "running" ? "正在发布…" : "发布 Live Tushare Session"}
            </button>
            <small>Token 只从部署环境读取，不进入页面或研究定义。</small>
          </>
        ) : (
          <>
            <button
              type="button"
              className="secondary-button"
              onClick={() => void onPublishFixtureSession()}
              disabled={publication === "running"}
            >
              {publication === "running"
                ? "正在发布…"
                : "发布下一 Fixture Session"}
            </button>
            <small>Fixture 仅用于验收；Live Workspace 请选择 Tushare Bootstrap。</small>
          </>
        )}
        {publication === "failed" && publicationError && (
          <span className="publication-error" role="alert">
            {publicationError}
          </span>
        )}
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

class ApiError extends Error {
  constructor(
    readonly reasonCode: string,
    message: string,
  ) {
    super(message);
  }
}

async function assertResponse(response: Response): Promise<Response> {
  if (!response.ok) {
    let reasonCode = `HTTP_${response.status}`;
    let message = `request failed with ${response.status}`;
    try {
      const payload = (await response.json()) as {
        detail?: { reason_code?: string; message?: string };
      };
      reasonCode = payload.detail?.reason_code ?? reasonCode;
      message = payload.detail?.message ?? message;
    } catch {
      // The status-based reason remains stable when a non-JSON gateway fails.
    }
    throw new ApiError(reasonCode, message);
  }
  return response;
}

function apiErrorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError
    ? `${error.reasonCode} · ${error.message}`
    : fallback;
}

function formatPercent(value: number | null): string {
  return value === null ? "—" : `${(value * 100).toFixed(2)}%`;
}

function definitionStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    queued: "RUN QUEUED",
    running: "RUNNING",
    succeeded: "SUCCEEDED",
    failed: "FAILED",
    cancelled: "CANCELLED",
    saved: "DRAFT SAVED",
    error: "NEEDS ATTENTION",
  };
  return labels[status] ?? "DRAFT";
}

function formatNumber(value: number | null): string {
  return value === null ? "—" : value.toFixed(4);
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}
