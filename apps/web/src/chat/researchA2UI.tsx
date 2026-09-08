import type { ActivityMessage } from "@ag-ui/core";
import {
  A2UIProvider,
  A2UIRenderer,
  createCatalog,
  type CatalogDefinitions,
  useA2UI,
} from "@copilotkit/a2ui-renderer";
import { useEffect, useId, useMemo, useState, type ReactNode } from "react";
import { z } from "zod";

import {
  parseResearchA2UINavigationHref,
  projectResearchA2UIContent,
  RESEARCH_A2UI_ACTIVITY_TYPE,
  RESEARCH_A2UI_CATALOG_ID,
} from "@thesistrace/contracts/research-a2ui";

import { ResearchResourceCards } from "./ResearchResourceCards";

const pairSchema = (labelLength: number, valueLength: number) => z.object({
  label: z.string().min(1).max(labelLength),
  value: z.string().min(1).max(valueLength),
}).strict();

export const researchA2UICatalogDefinitions = {
  Text: {
    description: "Bounded plain text.",
    props: z.object({
      text: z.string().min(1).max(4_000),
      variant: z.enum(["body", "caption", "label", "title"]).optional(),
    }).strict(),
  },
  Row: {
    description: "Horizontal child layout.",
    props: z.object({
      align: z.enum(["start", "center", "end", "stretch"]).optional(),
      children: z.array(z.string().min(1).max(64)).min(1).max(16),
      gap: z.enum(["compact", "normal", "wide"]).optional(),
    }).strict(),
  },
  Column: {
    description: "Vertical child layout.",
    props: z.object({
      align: z.enum(["start", "center", "end", "stretch"]).optional(),
      children: z.array(z.string().min(1).max(64)).min(1).max(16),
      gap: z.enum(["compact", "normal", "wide"]).optional(),
    }).strict(),
  },
  Divider: {
    description: "Hairline divider.",
    props: z.object({}).strict(),
  },
  Formula: {
    description: "Read-only Alpha formula with local copy.",
    props: z.object({
      expression: z.string().min(1).max(8_192),
      label: z.string().min(1).max(80).optional(),
    }).strict(),
  },
  AlphaProposal: {
    description: "Chat-owned Alpha proposal.",
    props: z.object({
      explanation: z.string().min(1).max(4_000),
      formula: z.string().min(1).max(8_192),
      hypothesis: z.string().min(1).max(2_000),
      period: z.string().min(1).max(120),
      researchType: z.string().min(1).max(80),
      strategy: z.array(pairSchema(80, 240)).min(1).max(16),
      title: z.string().min(1).max(160),
      universe: z.string().min(1).max(160),
    }).strict(),
  },
  ResearchRun: { description: "Current ResearchRun from Core.", props: z.object({ runId: z.string().regex(/^run_[a-f0-9]{20}$/) }).strict() },
  ResearchComparison: { description: "Ordered authoritative ResearchRuns.", props: z.object({ runIds: z.array(z.string().regex(/^run_[a-f0-9]{20}$/)).min(1).max(20) }).strict() },
  DailyTrack: { description: "Current DailyTrack from Core.", props: z.object({ trackId: z.string().regex(/^track_[a-f0-9]{20}$/) }).strict() },
  Table: {
    description: "Bounded read-only result table.",
    props: z.object({
      caption: z.string().min(1).max(240),
      columns: z.array(z.string().min(1).max(80)).min(1).max(12),
      initiallyExpanded: z.boolean().optional(),
      rows: z.array(z.array(z.string().max(320)).min(1).max(12)).max(100),
      summary: z.string().min(1).max(160),
    }).strict(),
  },
  Navigation: {
    description: "Allowlisted same-origin product navigation.",
    props: z.object({
      href: z.string().min(1).max(240),
      label: z.string().min(1).max(120),
    }).strict(),
  },
} satisfies CatalogDefinitions;

const researchA2UICatalog = createCatalog(
  researchA2UICatalogDefinitions,
  {
    Text: ({ props }) => (
      <p className={`chat-a2ui-text chat-a2ui-text-${props.variant ?? "body"}`}>
        {props.text}
      </p>
    ),
    Row: ({ children, props }) => (
      <div className={`chat-a2ui-row chat-a2ui-gap-${props.gap ?? "normal"} chat-a2ui-align-${props.align ?? "stretch"}`}>
        {props.children.map((id) => <span className="chat-a2ui-child" key={id}>{children(id)}</span>)}
      </div>
    ),
    Column: ({ children, props }) => (
      <div className={`chat-a2ui-column chat-a2ui-gap-${props.gap ?? "normal"} chat-a2ui-align-${props.align ?? "stretch"}`}>
        {props.children.map((id) => <div className="chat-a2ui-child" key={id}>{children(id)}</div>)}
      </div>
    ),
    Divider: () => <hr className="chat-a2ui-divider" />,
    Formula: ({ props }) => <FormulaSurface expression={props.expression} label={props.label} />,
    AlphaProposal: ({ props }) => (
      <section aria-label={`Alpha proposal: ${props.title}`} className="chat-a2ui-domain-section chat-a2ui-proposal">
        <header>
          <span>Alpha proposal</span>
          <strong>Chat-owned</strong>
        </header>
        <h2>{props.title}</h2>
        <dl className="chat-a2ui-facts">
          <Fact label="Hypothesis" value={props.hypothesis} wide />
          <Fact label="Universe" value={props.universe} />
          <Fact label="Period" value={props.period} />
          <Fact label="Research type" value={props.researchType} />
          {props.strategy.map((entry) => <Fact key={entry.label} label={entry.label} value={entry.value} />)}
        </dl>
        <div className="chat-a2ui-proposal-formula">
          <span>Formula</span>
          <code>{props.formula}</code>
        </div>
        <p>{props.explanation}</p>
      </section>
    ),
    ResearchRun: ({ props }) => <ResearchResourceCards kind="run" ids={[props.runId]} />,
    ResearchComparison: ({ props }) => <ResearchResourceCards kind="run" ids={props.runIds} />,
    DailyTrack: ({ props }) => <ResearchResourceCards kind="track" ids={[props.trackId]} />,
    Table: ({ props }) => <ResearchTable {...props} />,
    Navigation: ({ props }) => {
      const href = parseResearchA2UINavigationHref(props.href);
      return href === null ? (
        <p className="chat-a2ui-error" role="alert">This research link is unavailable.</p>
      ) : (
        <a className="chat-a2ui-navigation" href={href}>{props.label}</a>
      );
    },
  },
  {
    catalogId: RESEARCH_A2UI_CATALOG_ID,
    includeBasicCatalog: false,
  },
);

export function ResearchA2UIActivity({
  message,
}: {
  message: ActivityMessage;
}) {
  if (message.activityType !== RESEARCH_A2UI_ACTIVITY_TYPE) return null;
  const projection = projectResearchA2UIContent(message.content);
  if (projection.kind === "loading") {
    return (
      <article aria-label="Research surface is being prepared" className="chat-a2ui-lifecycle" role="status">
        <span aria-hidden="true" className="chat-a2ui-loading-mark" />
        <span>{projection.content.status === "retrying" ? "Rebuilding research view…" : "Building research view…"}</span>
      </article>
    );
  }
  if (projection.kind === "error") {
    return (
      <article className="chat-a2ui-error" role="alert">
        This research view could not be prepared. The conversation is still available.
        <small>Reference: {message.id} · {String(projection.content.errorCode)}</small>
      </article>
    );
  }
  const operationsJson = JSON.stringify(projection.content.a2ui_operations);
  return (
    <article aria-label="Research surface" className="chat-a2ui-surface">
      <A2UIProvider catalog={researchA2UICatalog} onAction={() => undefined}>
        <ReadyA2UIRenderer
          key={message.id}
          operationsJson={operationsJson}
        />
      </A2UIProvider>
    </article>
  );
}

function ReadyA2UIRenderer({ operationsJson }: { operationsJson: string }) {
  const { processMessages } = useA2UI();
  const operations = useMemo(() => (
    JSON.parse(operationsJson) as Array<Record<string, unknown>>
  ), [operationsJson]);
  const surfaceId = useMemo(() => readySurfaceId(operations), [operations]);
  useEffect(() => {
    processMessages(operations);
  }, [operations, processMessages]);
  return surfaceId === null ? (
    <p className="chat-a2ui-error" role="alert">
      This research surface could not be displayed. The conversation is still available.
    </p>
  ) : (
    <A2UIRenderer
      fallback={<span className="chat-a2ui-loading-mark" role="status" />}
      surfaceId={surfaceId}
    />
  );
}

function readySurfaceId(operations: readonly Record<string, unknown>[]): string | null {
  for (const operation of operations) {
    const create = isRecord(operation.createSurface) ? operation.createSurface : null;
    if (typeof create?.surfaceId === "string") return create.surfaceId;
    const update = isRecord(operation.updateComponents) ? operation.updateComponents : null;
    if (typeof update?.surfaceId === "string") return update.surfaceId;
  }
  return null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function FormulaSurface({ expression, label }: { expression: string; label?: string }) {
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  async function copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(expression);
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }
  }
  return (
    <section aria-label={label ?? "Alpha formula"} className="chat-a2ui-formula">
      <header>
        <span>{label ?? "Alpha formula"}</span>
        <button onClick={() => void copy()} type="button">Copy</button>
      </header>
      <code>{expression}</code>
      <span aria-live="polite" className="visually-hidden">
        {copyState === "copied" ? "Formula copied" : copyState === "failed" ? "Formula could not be copied" : ""}
      </span>
    </section>
  );
}

function ResearchTable({
  caption,
  columns,
  initiallyExpanded,
  rows,
  summary,
}: {
  caption: string;
  columns: string[];
  initiallyExpanded?: boolean;
  rows: string[][];
  summary: string;
}) {
  const headerId = useId();
  return (
    <LocalDisclosure initiallyExpanded={initiallyExpanded} summary={summary}>
      <div className="chat-a2ui-table-scroll">
        <table role="table">
          <caption>{caption}</caption>
          <thead role="rowgroup">
            <tr role="row">
              {columns.map((column, index) => (
                <th id={`${headerId}-${index}`} key={`${index}:${column}`} role="columnheader" scope="col">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody role="rowgroup">
            {rows.map((row, rowIndex) => (
              <tr key={`${rowIndex}:${row.join("\u0000")}`} role="row">
                {row.map((cell, columnIndex) => (
                  <td
                    data-label={columns[columnIndex]}
                    headers={`${headerId}-${columnIndex}`}
                    key={`${columnIndex}:${cell}`}
                    role="cell"
                  >
                    <span aria-hidden="true" className="chat-a2ui-cell-label">{columns[columnIndex]}</span>
                    <span className="chat-a2ui-cell-value">{cell}</span>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </LocalDisclosure>
  );
}

function LocalDisclosure({
  children,
  initiallyExpanded = false,
  summary,
}: {
  children: ReactNode;
  initiallyExpanded?: boolean;
  summary: string;
}) {
  const [expanded, setExpanded] = useState(initiallyExpanded);
  const contentId = useId();
  return (
    <section className="chat-a2ui-disclosure">
      <button
        aria-controls={contentId}
        aria-expanded={expanded}
        onClick={() => setExpanded((current) => !current)}
        type="button"
      >
        <span>{summary}</span>
        <span aria-hidden="true">{expanded ? "−" : "+"}</span>
      </button>
      {expanded ? <div id={contentId}>{children}</div> : null}
    </section>
  );
}

function Fact({ label, value, wide = false }: { label: string; value: string; wide?: boolean }) {
  return (
    <div className={wide ? "chat-a2ui-fact-wide" : undefined}>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
