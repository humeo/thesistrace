import type { ActivityMessage } from "@ag-ui/core";
import {
  A2UIProvider,
  A2UIRenderer,
  createCatalog,
  useA2UI,
} from "@copilotkit/a2ui-renderer";
import { useEffect, useId, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { z } from "zod";
import "../i18n";

import {
  parseResearchA2UINavigationHref,
  projectResearchA2UIContent,
  RESEARCH_A2UI_ACTIVITY_TYPE,
  RESEARCH_A2UI_CATALOG_ID,
  RESEARCH_A2UI_DEFINITIONS,
} from "@thesistrace/contracts/research-a2ui";

import { Alert, App, Card, Collapse, Descriptions, Divider, Flex, Spin, Table, Tag, Typography } from "antd";
import { ResearchResourceList } from "./ResearchResourceList";

export const researchA2UICatalogDefinitions = RESEARCH_A2UI_DEFINITIONS;

const researchA2UICatalog = createCatalog(
  researchA2UICatalogDefinitions,
  {
    Text: ({ props }) => props.variant === "title"
      ? <Typography.Title level={5} style={{ margin: 0 }}>{props.text}</Typography.Title>
      : <Typography.Text type={props.variant === "caption" ? "secondary" : undefined}
        strong={props.variant === "label"}>{props.text}</Typography.Text>,
    Row: ({ children, props }) => (
      <Flex wrap gap={16} align="stretch">
        {props.children.map((id) => <Flex vertical style={{ flex: 1, minWidth: 0 }} key={id}>{children(id)}</Flex>)}
      </Flex>
    ),
    Column: ({ children, props }) => (
      <Flex vertical gap={16} align="stretch">
        {props.children.map((id) => <Flex vertical style={{ minWidth: 0, maxWidth: "100%" }} key={id}>{children(id)}</Flex>)}
      </Flex>
    ),
    Divider: () => <Divider />,
    Formula: ({ props }) => <FormulaSurface expression={props.expression} label={props.label} />,
    AlphaProposal: ({ props }) => <AlphaProposalSurface props={props} />,
    ResearchRun: ({ props }) => <ResearchResourceList kind="run" ids={[props.runId]} />,
    ResearchComparison: ({ props }) => <ResearchResourceList kind="run" ids={props.runIds} />,
    DailyTrack: ({ props }) => <ResearchResourceList kind="track" ids={[props.trackId]} />,
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
        <Card size="small" title={props.title}
          extra={<Tag>{t("a2ui.chatOwned")}</Tag>}>
        <Flex vertical gap={16}><Typography.Text type="secondary">{t("a2ui.proposal")}</Typography.Text>
        <Descriptions size="small" column={2} items={[
          { key: "hypothesis", label: t("a2ui.hypothesis"), children: props.hypothesis, span: 2 },
          { key: "universe", label: t("a2ui.universe"), children: props.universe },
          { key: "period", label: t("a2ui.period"), children: props.period },
          { key: "researchType", label: t("a2ui.researchType"), children: props.researchType },
          ...props.strategy.map((entry, index) => ({ key: `strategy-${index}`, label: entry.label, children: entry.value })),
        ]} />
        <Flex vertical gap={8}>
          <Typography.Text>{t("a2ui.formulaWord")}</Typography.Text>
          <Typography.Text code style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{props.formula}</Typography.Text>
        </Flex>
        <Typography.Text>{props.explanation}</Typography.Text></Flex></Card>
      </section>
  );
}

function ResearchNavigation({ href: sourceHref, label }: { href: string; label: string }) {
  const { t } = useTranslation("chat");
  const href = parseResearchA2UINavigationHref(sourceHref);
  return href === null
    ? <Alert type="error" title={t("a2ui.unavailableLink")} />
    : <Typography.Link href={href}>{label}</Typography.Link>;
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
      <Flex gap={8} align="center" aria-label={t("a2ui.preparing")} role="status">
        <Spin size="small" />
        <Typography.Text>{t(projection.content.status === "retrying" ? "a2ui.rebuilding" : "a2ui.building")}</Typography.Text>
      </Flex>
    );
  }
  if (projection.kind === "error") {
    return (
      <Alert type="error" title={t("a2ui.preparationFailed")}
        description={t("a2ui.reference", { id: message.id, code: String(projection.content.errorCode) })} />
    );
  }
  const operationsJson = JSON.stringify(projection.content.a2ui_operations);
  return (
    <article aria-label={t("a2ui.surface")} style={{ minWidth: 0 }}>
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
    <Alert type="error" title={t("a2ui.displayFailed")} />
  ) : (
    <A2UIRenderer
      fallback={<span role="status" aria-label={t("a2ui.preparing")}><Spin /></span>}
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
  const { message } = App.useApp();
  const [copied, setCopied] = useState(false);
  return (
    <section aria-label={label ?? t("a2ui.formula")}>
      <Flex vertical gap={8}>
      <Flex align="center" justify="space-between">
        <Typography.Text>{label ?? t("a2ui.formula")}</Typography.Text>
        <Typography.Text copyable={{ text: expression, tooltips: [t("copy"), t("a2ui.formulaCopied")],
          onCopy: () => { setCopied(true); void message.success(t("a2ui.formulaCopied")); } }} />
      </Flex>
      <Typography.Text code style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{expression}</Typography.Text>
      <span className="sr-only">
        {copied ? t("a2ui.formulaCopied") : ""}
      </span>
      </Flex>
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
    <Collapse defaultActiveKey={initiallyExpanded ? ["table"] : []} items={[{
      key: "table", label: summary, forceRender: true,
      children: <Table size="small" pagination={false} scroll={{ x: "max-content" }}
        title={() => caption} aria-label={caption}
        columns={columns.map((column, index) => ({
          key: index, title: column, dataIndex: index,
          onHeaderCell: () => ({ id: `${headerId}-${index}`, role: "columnheader", scope: "col" }),
          onCell: () => ({ headers: `${headerId}-${index}`, role: "cell", "data-label": column }),
          render: (cell: string) => <><span aria-hidden="true" className="chat-a2ui-cell-label sr-only">{column}</span><span className="chat-a2ui-cell-value">{cell}</span></>,
        }))}
        dataSource={rows.map((row, key) => ({ ...row, key }))} />,
    }]} />
  );
}
