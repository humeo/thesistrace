import Decimal from "decimal.js";
import { Page, PageContent, PageHeader } from "../components/layout/Page";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Field, FieldGroup, FieldLabel } from "../components/ui/field";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Badge } from "../components/ui/badge";
import { Alert, AlertDescription } from "../components/ui/alert";
import { Empty, EmptyHeader, EmptyTitle } from "../components/ui/empty";
import { PageNavigation } from "../components/layout/PageNavigation";
import type { ParseKeys } from "i18next";
import { useRef, useState } from "react";
import { CaretDown, CaretUp, CaretUpDown } from "@phosphor-icons/react";
import { i18n, useTranslation } from "../i18n";
import { formatDecimal, formatNumber, formatPercent, formatUtcTimestamp } from "../i18n/format";
import { folderDisplayName } from "../research/folders";
import { followCoreLink } from "../shell/navigation";
import { formatRunError } from "./errors";
import type { ResearchRun } from "./ResearchRunsPage";
import { ResearchFolderLoadFailure } from "./ResearchFolderLoadFailure";
import { ResearchRunsNavigation } from "./ResearchRunsNavigation";
import { RESEARCH_RUN_PAGE_SIZE, type ResearchKindFilter, type ResearchMetricFilter, type ResearchRunSort, type ResearchRunSortKey, type ResearchRunSortDirection, type useResearchRunListController } from "./useResearchRunListController";

export function ResearchRunList({ list }: { list: ReturnType<typeof useResearchRunListController> }) {
  const { t } = useTranslation("runs");
  const { items, folders, folderFilter, researchKindFilter, pageIndex, sort, metricFilters, totalCount, folderError, error, loadState, refresh, refreshFolders, changeSort, changeFolderFilter, changeResearchKindFilter, showPreviousPage, showNextPage, applyMetricFilters } = list;
  const selectedFolder = folders.find(folder => folder.id === folderFilter);
  return <Page aria-label={t("title")} className="px-4 py-6 sm:px-6 lg:px-8">
    <PageContent className="flex flex-col gap-6">
      <PageHeader title={t("title")} />
      <ResearchRunsNavigation active="runs" />
      {folderError ? <ResearchFolderLoadFailure error={folderError} onRetry={refreshFolders} /> : null}
      <FieldGroup className="grid gap-4 sm:grid-cols-2">
        <Field>
          <FieldLabel htmlFor="runs-folder-filter">{t("folder")}</FieldLabel>
          <Select value={folderFilter} onValueChange={value => { if (value !== null) changeFolderFilter(value); }} disabled={folderError !== null}>
            <SelectTrigger id="runs-folder-filter" aria-label={t("filterFolder")} className="w-full"><SelectValue>{folderFilter ? (selectedFolder ? folderDisplayName(selectedFolder) : folderFilter) : t("allFolders")}</SelectValue></SelectTrigger>
            <SelectContent><SelectGroup>
              <SelectItem value="">{t("allFolders")}</SelectItem>
              {folders.map(folder => <SelectItem key={folder.id} value={folder.id}>{folderDisplayName(folder)}</SelectItem>)}
            </SelectGroup></SelectContent>
          </Select>
        </Field>
        <Field>
          <FieldLabel htmlFor="runs-kind-filter">{t("type")}</FieldLabel>
          <Select value={researchKindFilter} onValueChange={value => { if (value !== null) changeResearchKindFilter(value as ResearchKindFilter); }}>
            <SelectTrigger id="runs-kind-filter" aria-label={t("filterType")} className="w-full"><SelectValue>{researchKindFilter ? researchKindLabel(researchKindFilter) : t("allTypes")}</SelectValue></SelectTrigger>
            <SelectContent><SelectGroup>
              <SelectItem value="">{t("allTypes")}</SelectItem>
              <SelectItem value="factor_evaluation">{researchKindLabel("factor_evaluation")}</SelectItem>
              <SelectItem value="strategy_backtest">{researchKindLabel("strategy_backtest")}</SelectItem>
            </SelectGroup></SelectContent>
          </Select>
        </Field>
      </FieldGroup>
      {researchKindFilter !== "" ? <ResearchMetricFilters key={researchKindFilter} researchKind={researchKindFilter} filters={metricFilters} onApply={applyMetricFilters} /> : null}
      {error ? <Alert variant="destructive"><AlertDescription>{formatRunError(error)}<Button variant="outline" onClick={refresh}>{t("retry")}</Button></AlertDescription></Alert> : null}
      {loadState ? <p role="status" className="m-0 text-sm text-muted-foreground">{t("loadingRuns")}</p> : null}
      {loadState === null && !error && items?.length === 0 ? <Empty><EmptyHeader><EmptyTitle>{t("empty")}</EmptyTitle></EmptyHeader></Empty> : null}
      <ResearchRunHistory items={items ?? []} researchKind={researchKindFilter} sort={sort} onSortChange={changeSort} />
      <ResearchRunPagination totalCount={totalCount} loading={loadState !== null || error !== null} onNextPage={showNextPage} onPreviousPage={showPreviousPage} pageIndex={pageIndex} />
    </PageContent>
  </Page>;
}

export function ResearchRunPagination({
  totalCount,
  loading,
  onNextPage,
  onPreviousPage,
  pageIndex,
}: {
  totalCount: number | null;
  loading: boolean;
  onNextPage: () => void;
  onPreviousPage: () => void;
  pageIndex: number;
}) {
  const { t } = useTranslation("runs");
  return <PageNavigation label={t("pages")} previousLabel={t("previous")} nextLabel={t("next")}
    previousDisabled={loading || pageIndex === 0} nextDisabled={loading || totalCount === null || (pageIndex + 1) * RESEARCH_RUN_PAGE_SIZE >= totalCount}
    onPrevious={onPreviousPage} onNext={onNextPage}>
    <span>{totalCount === null ? t("loading") : t("total", { total: formatNumber(totalCount), size: formatNumber(RESEARCH_RUN_PAGE_SIZE) })}</span>
    {totalCount !== null ? <span>{t("page", { page: formatNumber(totalCount === 0 ? 0 : pageIndex + 1), pages: formatNumber(Math.ceil(totalCount / RESEARCH_RUN_PAGE_SIZE)) })}</span> : null}
  </PageNavigation>;
}

type ResearchRunMetricColumn = {
  key: Exclude<ResearchRunSortKey, "created_at">;
  label: ParseKeys<"runs">;
  shortLabel: ParseKeys<"runs">;
};

const FACTOR_RESEARCH_RUN_METRICS: ResearchRunMetricColumn[] = [
  { key: "one_session_rank_ic", label: "metrics.one_session_rank_ic", shortLabel: "shortMetrics.one_session_rank_ic" },
  { key: "five_session_rank_ic", label: "metrics.five_session_rank_ic", shortLabel: "shortMetrics.five_session_rank_ic" },
  { key: "twenty_session_rank_ic", label: "metrics.twenty_session_rank_ic", shortLabel: "shortMetrics.twenty_session_rank_ic" },
];

const STRATEGY_RESEARCH_RUN_METRICS: ResearchRunMetricColumn[] = [
  {
    key: "annualized_excess_return",
    label: "metrics.annualized_excess_return",
    shortLabel: "shortMetrics.annualized_excess_return",
  },
  { key: "sharpe", label: "metrics.sharpe", shortLabel: "shortMetrics.sharpe" },
  { key: "maximum_drawdown", label: "metrics.maximum_drawdown", shortLabel: "shortMetrics.maximum_drawdown" },
];

type MetricFilterDraft = Omit<ResearchMetricFilter, "value"> & { id: number; value: string };

export function ResearchMetricFilters({ researchKind, filters, onApply }: {
  researchKind: Exclude<ResearchKindFilter, "">;
  filters: ResearchMetricFilter[];
  onApply: (filters: ResearchMetricFilter[]) => void;
}) {
  const { t } = useTranslation("runs");
  const columns = researchKind === "strategy_backtest"
    ? STRATEGY_RESEARCH_RUN_METRICS
    : FACTOR_RESEARCH_RUN_METRICS;
  const [rows, setRows] = useState<MetricFilterDraft[]>(() => filters.map((filter, id) => ({ ...filter, id, value: new Decimal(filter.value).mul(isPercentMetric(filter.metric) ? 100 : 1).toString() })));
  const [applied, setApplied] = useState(() => JSON.stringify(rows));
  const nextId = useRef(rows.length);
  const dirty = JSON.stringify(rows) !== applied;
  function update(id: number, values: Partial<MetricFilterDraft>) {
    setRows(current => current.map(row => row.id === id ? { ...row, ...values } : row));
  }
  return (
    <form className="flex flex-col gap-4 border-b border-border pb-6" aria-label={t("filters.title")} onSubmit={event => {
      event.preventDefault();
      onApply(rows.map(row => ({ metric: row.metric, operator: row.operator,
        value: new Decimal(row.value).div(isPercentMetric(row.metric) ? 100 : 1).toNumber() })));
      setApplied(JSON.stringify(rows));
    }}>
      <div className="flex flex-wrap items-center gap-2">
        <span>{t("filters.title")}</span>
        <Button variant="outline" type="button" disabled={rows.length >= 12} onClick={() => {
          const id = nextId.current++;
          setRows(current => [...current, { id, metric: columns[0].key, operator: "gt", value: "" }]);
        }}>{t("filters.add")}</Button>
        {(rows.length > 0 || applied !== "[]") && <>
          <Button variant="outline" type="submit" disabled={!dirty}>{t("filters.apply")}</Button>
          <Button variant="outline" type="button" onClick={() => { setRows([]); setApplied("[]"); onApply([]); }}>{t("filters.clear")}</Button>
        </>}
      </div>
      {rows.length > 0 && <p>{t("filters.allMatch")}{researchKind === "strategy_backtest" && t("filters.percent")}</p>}
      <FieldGroup className="gap-4">{rows.map((row, index) => (
        <FieldGroup className="grid items-end gap-3 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_auto]" key={row.id}>
          <Field>
            <FieldLabel htmlFor={"metric-" + row.id}>{t("filters.metric")}</FieldLabel>
            <Select value={row.metric} onValueChange={value => { if (value) update(row.id, { metric: value as ResearchMetricFilter["metric"], value: "" }); }}>
              <SelectTrigger id={"metric-" + row.id} aria-label={t("filters.metricAt", { index: formatNumber(index + 1) })} className="w-full"><SelectValue>{t(columns.find(column => column.key === row.metric)!.label)}</SelectValue></SelectTrigger>
              <SelectContent><SelectGroup>{columns.map(column => <SelectItem key={column.key} value={column.key}>{t(column.label)}</SelectItem>)}</SelectGroup></SelectContent>
            </Select>
          </Field>
          <Field>
            <FieldLabel htmlFor={"comparison-" + row.id}>{t("filters.comparison")}</FieldLabel>
            <Select value={row.operator} onValueChange={value => { if (value) update(row.id, { operator: value as ResearchMetricFilter["operator"] }); }}>
              <SelectTrigger id={"comparison-" + row.id} aria-label={t("filters.comparisonAt", { index: formatNumber(index + 1) })} className="w-full"><SelectValue>{{ gt: ">", gte: "≥", lt: "<", lte: "≤" }[row.operator]}</SelectValue></SelectTrigger>
              <SelectContent><SelectGroup><SelectItem value="gt">&gt;</SelectItem><SelectItem value="gte">≥</SelectItem><SelectItem value="lt">&lt;</SelectItem><SelectItem value="lte">≤</SelectItem></SelectGroup></SelectContent>
            </Select>
          </Field>
          <Field>
            <FieldLabel htmlFor={"threshold-" + row.id}>{t(isPercentMetric(row.metric) ? "filters.valuePercent" : "filters.value")}</FieldLabel>
            <Input id={"threshold-" + row.id} aria-label={t("filters.thresholdAt", { index: formatNumber(index + 1) })} type="number" step="any" required value={row.value} onChange={event => update(row.id, { value: event.target.value })} />
          </Field>
          <Button variant="outline" type="button" aria-label={t("filters.removeAt", { index: formatNumber(index + 1) })} onClick={() => setRows(current => current.filter(item => item.id !== row.id))}>{t("filters.remove")}</Button>
        </FieldGroup>
      ))}</FieldGroup>
      {dirty && <p role="status">{t("filters.notApplied")}</p>}
    </form>
  );
}

function isPercentMetric(metric: ResearchMetricFilter["metric"]): boolean {
  return metric === "annualized_excess_return" || metric === "maximum_drawdown";
}

export function ResearchRunHistory({
  items,
  researchKind = "",
  sort,
  onSortChange,
}: {
  items: ResearchRun[];
  researchKind?: ResearchKindFilter;
  sort: ResearchRunSort;
  onSortChange: (sort: ResearchRunSort) => void;
}) {
  const { t } = useTranslation("runs");
  const metricColumns = researchRunMetricColumns(researchKind);

  function changeSort(key: ResearchRunSortKey) {
    onSortChange({ key, direction: sort.key === key
      ? (sort.direction === "ascending" ? "descending" : "ascending")
      : defaultResearchRunSortDirection(key) });
  }

  function selectSort(key: ResearchRunSortKey) {
    onSortChange({ key, direction: defaultResearchRunSortDirection(key) });
  }

  function toggleSortDirection() {
    onSortChange({ ...sort, direction: sort.direction === "ascending" ? "descending" : "ascending" });
  }

  const MobileSortIcon = sort.direction === "ascending" ? CaretUp : CaretDown;

  return (
    <div className="min-w-0">
      <FieldGroup className="mb-4 flex-row items-end gap-3 sm:hidden">
        <Field className="min-w-0 flex-1">
          <FieldLabel htmlFor="runs-sort">{t("sortBy")}</FieldLabel>
          <Select value={sort.key} onValueChange={value => { if (value) selectSort(value as ResearchRunSortKey); }}>
            <SelectTrigger id="runs-sort" aria-label={t("sortByAria")} className="w-full"><SelectValue>{sort.key === "created_at" ? t("created") : t([...FACTOR_RESEARCH_RUN_METRICS, ...STRATEGY_RESEARCH_RUN_METRICS].find(column => column.key === sort.key)!.label)}</SelectValue></SelectTrigger>
            <SelectContent><SelectGroup><SelectItem value="created_at">{t("created")}</SelectItem>{metricColumns.map(column => <SelectItem key={column.key} value={column.key}>{t(column.label)}</SelectItem>)}</SelectGroup></SelectContent>
          </Select>
        </Field>
        <Button variant="outline" aria-label={t(sort.direction === "ascending" ? "sortAscending" : "sortDescending")} onClick={toggleSortDirection}><MobileSortIcon data-icon="inline-start" />{t(sort.direction === "ascending" ? "ascending" : "descending")}</Button>
      </FieldGroup>
      <div className="min-w-0">
      <Table aria-label={t("title")} scrollLabel={t("title")} className="min-w-[880px]">
        <TableHeader>
          <TableRow>
            <TableHead scope="col">{i18n.t("research:title")}</TableHead>
            <TableHead scope="col">{t("type")}</TableHead>
            <SortableResearchRunHeading
              direction={sort.direction}
              isActive={sort.key === "created_at"}
              label={t("createdUtc")}
              onSort={() => changeSort("created_at")}
            />
            <TableHead scope="col">{t("status")}</TableHead>
            {metricColumns.length === 0 ? (
              <TableHead className="text-right" scope="col">{t("resultSummary")}</TableHead>
            ) : metricColumns.map((column) => (
              <SortableResearchRunHeading
                direction={sort.direction}
                isActive={sort.key === column.key}
                key={column.key}
                label={t(column.label)}
                onSort={() => changeSort(column.key)}
              />
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((item) => (
            <TableRow key={item.id}>
              <TableCell className="min-w-48 max-w-80 whitespace-normal break-words font-medium">
                <a className="block min-h-11 w-full content-center text-primary underline-offset-4 hover:underline md:min-h-0" href={`/research-runs/${encodeURIComponent(item.id)}`} onClick={followCoreLink}>{item.name}</a>
              </TableCell>
              <TableCell data-label={t("type")}>{researchKindLabel(item.research_kind)}</TableCell>
              <TableCell data-label={t("createdUtc")}>
                <time dateTime={item.created_at}>{formatResearchRunCreatedAt(item.created_at)}</time>
              </TableCell>
              <TableCell data-label={t("status")}><Badge variant={item.status === "failed" ? "destructive" : item.status === "succeeded" ? "default" : "outline"}>{t(`statuses.${item.status}`)}</Badge></TableCell>
              {metricColumns.length === 0 ? (
                <ResearchRunResultSummary item={item} />
              ) : metricColumns.map((column) => (
                <TableCell className="text-right font-mono tabular-nums" data-label={t(column.label)} key={column.key}>
                  {formatResearchRunMetric(item, column.key)}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      </div>
    </div>
  );
}

function ResearchRunResultSummary({ item }: { item: ResearchRun }) {
  const { t } = useTranslation("runs");
  const columns = item.research_kind === "factor_evaluation"
    ? FACTOR_RESEARCH_RUN_METRICS
    : STRATEGY_RESEARCH_RUN_METRICS;
  return (
    <TableCell className="text-right" data-label={t("resultSummary")}>
      <div className="flex justify-end gap-4">
        {columns.map((column) => (
          <span className="grid gap-1" key={column.key}>
            <span className="text-xs text-muted-foreground">{t(column.shortLabel)}</span>
            <strong className="font-mono font-medium tabular-nums">{formatResearchRunMetric(item, column.key)}</strong>
          </span>
        ))}
      </div>
    </TableCell>
  );
}

function researchRunMetricColumns(
  researchKind: ResearchKindFilter,
): ResearchRunMetricColumn[] {
  if (researchKind === "factor_evaluation") return FACTOR_RESEARCH_RUN_METRICS;
  if (researchKind === "strategy_backtest") return STRATEGY_RESEARCH_RUN_METRICS;
  return [];
}

function defaultResearchRunSortDirection(
  key: ResearchRunSortKey,
): ResearchRunSortDirection {
  return key === "maximum_drawdown" ? "ascending" : "descending";
}

function SortableResearchRunHeading({
  direction,
  isActive,
  label,
  onSort,
}: {
  direction: ResearchRunSortDirection;
  isActive: boolean;
  label: string;
  onSort: () => void;
}) {
  const Icon = isActive
    ? direction === "ascending" ? CaretUp : CaretDown
    : CaretUpDown;
  return (
    <TableHead aria-sort={isActive ? direction : "none"} scope="col">
      <Button variant="ghost" className="-ml-3" onClick={onSort} type="button">
        {label}
        <Icon aria-hidden="true" data-icon="inline-end" />
      </Button>
    </TableHead>
  );
}

export function formatResearchRunCreatedAt(value: string): string {
  return formatUtcTimestamp(value);
}

function researchRunSortValue(item: ResearchRun, key: ResearchRunSortKey): number | null {
  if (key === "created_at") {
    const value = new Date(item.created_at).getTime();
    return Number.isFinite(value) ? value : null;
  }
  const metrics = item.key_metrics;
  if (key === "annualized_excess_return" || key === "sharpe" || key === "maximum_drawdown") {
    return metrics?.research_kind === "strategy_backtest" ? metrics[key] : null;
  }
  return metrics?.research_kind === "factor_evaluation" ? metrics[key] : null;
}

function formatResearchRunMetric(
  item: ResearchRun,
  key: Exclude<ResearchRunSortKey, "created_at">,
): string {
  const value = researchRunSortValue(item, key);
  if (value === null) return "—";
  if (key === "annualized_excess_return") return formatSignedPercent(value);
  if (key === "maximum_drawdown") return formatPercent(value);
  return formatDecimal(value);
}


function formatSignedPercent(value: number | null) { return formatPercent(value, { signed: true }); }
function researchKindLabel(value: ResearchRun["research_kind"]) { return i18n.t(`research:${value}`); }
