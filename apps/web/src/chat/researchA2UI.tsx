import type { ActivityMessage } from "@ag-ui/core";
import {
  A2UIProvider,
  A2UIRenderer,
  createCatalog,
  type CatalogDefinitions,
  useA2UI,
} from "@copilotkit/a2ui-renderer";
import { useEffect, useId, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { z } from "zod";
import "../i18n";

import {
  parseResearchA2UINavigationHref,
  projectResearchA2UIContent,
  RESEARCH_A2UI_ACTIVITY_TYPE,
  RESEARCH_A2UI_CATALOG_ID,
} from "@thesistrace/contracts/research-a2ui";

import { cn } from "cn";
import { CaretDown } from "@phosphor-icons/react";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Card, CardHeader, CardTitle, CardContent } from "../components/ui/card";
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "../components/ui/collapsible";
import { Separator } from "../components/ui/separator";
import { Spinner } from "../components/ui/spinner";
import { Alert, AlertDescription } from "../components/ui/alert";
import { toast } from "../components/ui/toast";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell, TableCaption } from "../components/ui/table";
import styles from "./A2UISurfaces.module.css";
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
      <p className={cn(styles.text, styles[props.variant ?? "body"])}>
        {props.text}
      </p>
    ),
    Row: ({ children, props }) => (
      <div className={cn(styles.row, styles[props.gap ?? "normal"], styles[props.align ?? "stretch"])}>
        {props.children.map((id) => <span className={styles.child} key={id}>{children(id)}</span>)}
      </div>
    ),
    Column: ({ children, props }) => (
      <div className={cn(styles.column, styles[props.gap ?? "normal"], styles[props.align ?? "stretch"])}>
        {props.children.map((id) => <div className={styles.child} key={id}>{children(id)}</div>)}
      </div>
    ),
    Divider: () => <Separator />,
    Formula: ({ props }) => <FormulaSurface expression={props.expression} label={props.label} />,
    AlphaProposal: ({ props }) => <AlphaProposalSurface props={props} />,
    ResearchRun: ({ props }) => <ResearchResourceCards kind="run" ids={[props.runId]} />,
    ResearchComparison: ({ props }) => <ResearchResourceCards kind="run" ids={props.runIds} />,
    DailyTrack: ({ props }) => <ResearchResourceCards kind="track" ids={[props.trackId]} />,
    Table: ({ props }) => <ResearchTable {...props} />,
    Navigation: ({ props }) => <ResearchNavigation href={props.href} label={props.label} />,
  },
  {
    catalogId: RESEARCH_A2UI_CATALOG_ID,
    includeBasicCatalog: false,
  },
);

function AlphaProposalSurface({ props }: { props: z.infer<typeof researchA2UICatalogDefinitions.AlphaProposal.props> }) {
  const { t } = useTranslation("chat");
  return (
      <section aria-label={t("a2ui.alphaProposal", { title: props.title })} >
        <Card><CardHeader>
          <div className={styles.row}><span>{t("a2ui.proposal")}</span><Badge variant="secondary">{t("a2ui.chatOwned")}</Badge></div>
          <CardTitle role="heading" aria-level={2}>{props.title}</CardTitle>
        </CardHeader><CardContent className={styles.column}>
        <dl className={styles.facts}>
          <Fact label={t("a2ui.hypothesis")} value={props.hypothesis} wide />
          <Fact label={t("a2ui.universe")} value={props.universe} />
          <Fact label={t("a2ui.period")} value={props.period} />
          <Fact label={t("a2ui.researchType")} value={props.researchType} />
          {props.strategy.map((entry) => <Fact key={entry.label} label={entry.label} value={entry.value} />)}
        </dl>
        <div className={styles.column}>
          <span>{t("a2ui.formulaWord")}</span>
          <code className={styles.code}>{props.formula}</code>
        </div>
        <p>{props.explanation}</p></CardContent></Card>
      </section>
  );
}

function ResearchNavigation({ href: sourceHref, label }: { href: string; label: string }) {
  const { t } = useTranslation("chat");
  const href = parseResearchA2UINavigationHref(sourceHref);
  return href === null
    ? <Alert variant="destructive">{t("a2ui.unavailableLink")}</Alert>
    : <Button variant="link" className="h-auto min-h-11 max-w-full whitespace-normal text-left" nativeButton={false} role="link" render={<a href={href} />}>{label}</Button>;
}

export function ResearchA2UIActivity({
  message,
}: {
  message: ActivityMessage;
}) {
  const { t } = useTranslation("chat");
  if (message.activityType !== RESEARCH_A2UI_ACTIVITY_TYPE) return null;
  const projection = projectResearchA2UIContent(message.content);
  if (projection.kind === "loading") {
    return (
      <article aria-label={t("a2ui.preparing")} className={styles.row} role="status">
        <Spinner aria-hidden="true" />
        <span>{t(projection.content.status === "retrying" ? "a2ui.rebuilding" : "a2ui.building")}</span>
      </article>
    );
  }
  if (projection.kind === "error") {
    return (
      <Alert variant="destructive">
        {t("a2ui.preparationFailed")}
        <AlertDescription>{t("a2ui.reference", { id: message.id, code: String(projection.content.errorCode) })}</AlertDescription>
      </Alert>
    );
  }
  const operationsJson = JSON.stringify(projection.content.a2ui_operations);
  return (
    <article aria-label={t("a2ui.surface")} className={styles.surface}>
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
  const { t } = useTranslation("chat");
  const { processMessages } = useA2UI();
  const operations = useMemo(() => (
    JSON.parse(operationsJson) as Array<Record<string, unknown>>
  ), [operationsJson]);
  const surfaceId = useMemo(() => readySurfaceId(operations), [operations]);
  useEffect(() => {
    processMessages(operations);
  }, [operations, processMessages]);
  return surfaceId === null ? (
    <Alert variant="destructive">{t("a2ui.displayFailed")}</Alert>
  ) : (
    <A2UIRenderer
      fallback={<Spinner role="status" aria-label={t("a2ui.preparing")} />}
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
  const { t } = useTranslation("chat");
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  async function copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(expression);
      setCopyState("copied");
      toast.add({ title: <FormulaCopyFeedback message="a2ui.formulaCopied" />, type: "success" });
    } catch {
      setCopyState("failed");
      toast.add({ title: <FormulaCopyFeedback message="a2ui.formulaCopyFailed" />, type: "error" });
    }
  }
  return (
    <section aria-label={label ?? t("a2ui.formula")} className={styles.formula}>
      <header className={styles.row}>
        <span>{label ?? t("a2ui.formula")}</span>
        <Button variant="outline" onClick={() => void copy()}>{t("copy")}</Button>
      </header>
      <code className={styles.code}>{expression}</code>
      <span className="sr-only">
        {copyState === "copied" ? t("a2ui.formulaCopied") : copyState === "failed" ? t("a2ui.formulaCopyFailed") : ""}
      </span>
    </section>
  );
}

function FormulaCopyFeedback({ message }: { message: "a2ui.formulaCopied" | "a2ui.formulaCopyFailed" }) {
  const { t } = useTranslation("chat");
  return t(message);
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
      <div className={styles.child}>
        <Table role="table" scrollLabel={caption}>
          <TableCaption>{caption}</TableCaption>
          <TableHeader role="rowgroup">
            <TableRow role="row">
              {columns.map((column, index) => (
                <TableHead id={`${headerId}-${index}`} key={`${index}:${column}`} role="columnheader" scope="col">
                  {column}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody role="rowgroup">
            {rows.map((row, rowIndex) => (
              <TableRow key={`${rowIndex}:${row.join("\u0000")}`} role="row">
                {row.map((cell, columnIndex) => (
                  <TableCell
                    data-label={columns[columnIndex]}
                    headers={`${headerId}-${columnIndex}`}
                    key={`${columnIndex}:${cell}`}
                    role="cell"
                  >
                    <span aria-hidden="true" className="chat-a2ui-cell-label sr-only">{columns[columnIndex]}</span>
                    <span className="chat-a2ui-cell-value">{cell}</span>
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
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
  return <Collapsible defaultOpen={initiallyExpanded} className="min-w-0 rounded-lg border border-border">
    <CollapsibleTrigger render={<Button variant="ghost" className="h-auto min-h-11 w-full justify-between whitespace-normal p-3 text-left" />}>
      {summary}<CaretDown aria-hidden="true" data-icon="inline-end" />
    </CollapsibleTrigger>
    <CollapsibleContent keepMounted className="min-w-0 p-3">{children}</CollapsibleContent>
  </Collapsible>;
}

function Fact({ label, value, wide = false }: { label: string; value: string; wide?: boolean }) {
  return (
    <div className={cn(wide && styles.wide)}>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
