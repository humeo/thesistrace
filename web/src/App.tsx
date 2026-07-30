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

type RunStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

type ResearchResult = {
  manifest: {
    id: string;
    research_run_id: string;
    dataset_release: { id: string };
    definition: { id: string; content_hash: string };
    calculation_kernel: string;
  };
  factor_evaluation: {
    horizons: Record<
      string,
      {
        summary: {
          ic: { mean: number | null; icir: number | null };
          rank_ic: { mean: number | null; icir: number | null };
          top_bottom_return: number | null;
        };
      }
    >;
  };
  strategy_backtest: {
    metrics: {
      net_cumulative_return: number;
      net_cagr: number | null;
      benchmark_cumulative_return: number;
      annualized_excess_return: number | null;
      maximum_drawdown: { value: number };
      sharpe: number | null;
      turnover: { annualized: number | null };
      transaction_costs: { cumulative_amount: number };
    };
  };
};

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
              <>
                <DataContractPanel releaseId={state.workspace.latest_dataset_release.id} />
                <ResearchDefinitionEditor />
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
    try {
      await saveDraft();
    } catch {
      setStatus("error");
      setErrors(["Draft 保存失败"]);
    }
  }

  async function handleRun() {
    try {
      const currentDraftId = draftId ?? (await saveDraft());
      setStatus("running");
      setErrors([]);
      const response = await fetch(`/api/v1/research-definitions/${currentDraftId}/runs`, {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
      });
      if (!response.ok) {
        const payload = (await response.json()) as {
          detail?: { errors?: { location: string; message: string }[] };
        };
        setErrors(
          payload.detail?.errors?.map((item) => `${item.location}: ${item.message}`) ?? [
            "研究定义验证失败",
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
    } catch {
      setStatus("error");
      setErrors(["ResearchRun 创建失败"]);
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
          diagnostic: { message?: string } | null;
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
        const message = run.attempts.at(-1)?.diagnostic?.message;
        setErrors([message ?? `ResearchRun ${run.status}`]);
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
            diagnostic: { message?: string } | null;
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
        const message = run.attempts.at(-1)?.diagnostic?.message;
        setErrors([message ?? `ResearchRun ${run.status}`]);
      }
    } catch {
      setErrors(["最近一次 ResearchRun 状态读取失败"]);
    }
  }

  return (
    <section className="definition-panel">
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
        <button type="button" className="secondary-button" onClick={handleSave}>
          保存 Draft
        </button>
        <button
          type="button"
          className="bootstrap-button"
          onClick={handleRun}
          disabled={status === "queued" || status === "running"}
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
  const metrics = result.strategy_backtest.metrics;
  const [track, setTrack] = useState<{
    id: string;
    status: "active" | "stopped";
    current_generation_id: string;
    head: { target_dataset_release_id: string };
    advances: { status: string }[];
  } | null>(null);
  const [trackingError, setTrackingError] = useState(false);
  const [trackingView, setTrackingView] = useState<{
    checkpoint: { id: string; kind: string };
    strategy: {
      daily: { net_nav: string; session: string }[];
    };
  } | null>(null);

  useEffect(() => {
    fetch("/api/v1/daily-tracks")
      .then(assertResponse)
      .then((response) => response.json())
      .then(
        (payload: {
          items: ({
            seed_run_id: string;
          } & NonNullable<typeof track>)[];
        }) => {
          setTrack(
            payload.items.find(
              (item) => item.seed_run_id === result.manifest.research_run_id,
            ) ?? null,
          );
        },
      )
      .catch(() => setTrackingError(true));
  }, [result.manifest.research_run_id]);

  useEffect(() => {
    if (!track) {
      setTrackingView(null);
      return;
    }
    fetch(`/api/v1/daily-tracks/${track.id}/current`)
      .then(assertResponse)
      .then((response) => response.json())
      .then(setTrackingView)
      .catch(() => setTrackingError(true));
  }, [track]);

  async function activateTracking() {
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
      setTrack(await response.json());
    } catch {
      setTrackingError(true);
    }
  }

  async function stopTracking() {
    if (!track) {
      return;
    }
    try {
      const response = await fetch(`/api/v1/daily-tracks/${track.id}/stop`, {
        method: "POST",
      }).then(assertResponse);
      setTrack(await response.json());
    } catch {
      setTrackingError(true);
    }
  }

  return (
    <section className="result-panel" aria-label="ResearchRun 结果">
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
      <div className="tracking-control">
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
                  {trackingView.strategy.daily.at(-1)?.net_nav}
                </small>
              )}
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
        {trackingError && <span className="tracking-error">追踪状态读取失败</span>}
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
