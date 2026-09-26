import { cn } from "cn";
import { Page, PageHeader, PageContent, Section } from "../components/layout/Page";
import { PageNavigation } from "../components/layout/PageNavigation";
import { Disclosure } from "../components/layout/Disclosure";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Alert, AlertDescription } from "../components/ui/alert";
import { Empty, EmptyHeader, EmptyTitle } from "../components/ui/empty";
import { Field, FieldGroup, FieldLabel } from "../components/ui/field";
import { InputGroup, InputGroupInput, InputGroupAddon, InputGroupButton } from "../components/ui/input-group";
import { ToggleGroup, ToggleGroupItem } from "../components/ui/toggle-group";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectGroup, SelectItem } from "../components/ui/select";
import { Table, TableHeader, TableHead, TableRow, TableBody, TableCell, TableCaption } from "../components/ui/table";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetClose } from "../components/ui/sheet";
import { toast } from "../components/ui/toast";
import { ArrowClockwise, Copy, MagnifyingGlass, X } from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";

import type { AlphaCatalog, AlphaCatalogField } from "../alphaCatalog";
import { coreFetch } from "../auth/coreFetch";
import { useTranslation } from "../i18n";
import { builtinDisplay, catalogLabel, compareResearchPurposes, fieldDisplay, matchesResearchField } from "../i18n/catalog";

type FinancialResearchReadiness =
  | "ready"
  | "ready_with_pending"
  | "ready_with_gaps"
  | "not_ready";

export type FieldFamilyAvailability = {
  family_id: string;
  research_category: "market" | "financial";
  source_endpoints: string[];
  supported_field_ids: string[];
  available_field_ids: string[];
  coverage_start: string | null;
  coverage_end: string | null;
  readiness: FinancialResearchReadiness | "partial";
};

export type DataOverview = {
  generation_manifest_sha256: string | null;
  available_field_ids: string[];
  field_families: FieldFamilyAvailability[];
  market_coverage: { start: string; end: string } | null;
  financial_coverage: {
    start: string;
    discovery_baseline_session: string;
    discovery_attempted_through_session: string;
    discovery_complete_through_session: string;
    historical_reconciliation_watermark: string;
    revision_coverage: string;
    seed_policy: string;
    readiness_status: Exclude<FinancialResearchReadiness, "not_ready">;
    pending_instrument_count: number;
    discovery_gap_count: number;
    earliest_unresolved_date: string | null;
    sparse_facts: boolean;
  } | null;
  industry_coverage: {
    start: string;
    observation_through_session: string;
    classification_version: "SW2021";
  } | null;
  benchmark_coverage: { start: string; end: string } | null;
  benchmark_snapshot_sha256: string | null;
  benchmark_last_published_at: string | null;
  data_through_session: string | null;
  last_market_refresh_at: string | null;
  last_financial_refresh_at: string | null;
  last_industry_refresh_at: string | null;
  industry_refresh_status: "running" | "succeeded" | "failed" | null;
  industry_refresh_failure_code: string | null;
  market_research_readiness: boolean;
  benchmark_research_readiness: boolean;
  financial_research_readiness: FinancialResearchReadiness;
  industry_research_readiness: boolean;
};

export type DataSnapshot = DataOverview & { catalog: AlphaCatalog };

type DataPageResources = {
  overview: DataOverview;
  catalog: AlphaCatalog;
};

export type DataPageLoad =
  | { resources: DataPageResources; error: null }
  | { resources: null; error: "unavailable" };

export async function loadDataPage(
  request: typeof fetch = coreFetch,
): Promise<DataPageLoad> {
  try {
    const response = await request("/api/data");
    if (!response.ok) {
      throw new Error("Data unavailable");
    }
    const { catalog, ...overview } = await response.json() as DataSnapshot;
    return { resources: { overview, catalog }, error: null };
  } catch {
    return { resources: null, error: "unavailable" };
  }
}

export function DataOverviewView({
  catalog,
  overview,
  onRefresh,
  refreshing = false,
  error,
}: {
  catalog: AlphaCatalog;
  overview: DataOverview;
  onRefresh: () => void;
  refreshing?: boolean;
  error?: "unavailable" | null;
}) {
  const { t } = useTranslation("data");
  const financial = overview.financial_coverage;
  const marketFamilies = overview.field_families.filter((family) => family.research_category === "market");
  const financialFamilies = overview.field_families.filter((family) => family.research_category === "financial");
  const industryState = overview.industry_research_readiness ? "ready"
    : overview.industry_coverage ? "partial" : "not_ready";
  const rows = [
    { id: "market" as const, description: t("marketDescription"), coverage: overview.market_coverage,
      state: categoryReadiness(marketFamilies), families: marketFamilies },
    { id: "financial" as const, description: t("financialDescription"),
      coverage: financial ? { start: financial.start, end: financial.discovery_complete_through_session } : null,
      state: categoryReadiness(financialFamilies), families: financialFamilies },
    { id: "industry" as const, description: t("industryDescription"),
      coverage: overview.industry_coverage ? { start: overview.industry_coverage.start,
        end: overview.industry_coverage.observation_through_session } : null,
      state: industryState, families: [] },
    { id: "benchmark" as const, description: catalogLabel("benchmarks", "csi300-price-index-open"),
      coverage: overview.benchmark_coverage,
      state: overview.benchmark_research_readiness ? "ready" : "not_ready", families: [] },
  ];
  return <Page aria-label={t("title")} className="px-4 py-6 sm:px-6 lg:px-8"><PageContent className="flex flex-col gap-6">
    <PageHeader title={t("title")} description={t("introduction")} actions={<Button variant="outline" onClick={onRefresh} disabled={refreshing}><ArrowClockwise aria-hidden="true" data-icon="inline-start" />{t("reload")}</Button>} />
    {error && <Alert variant="destructive"><AlertDescription>{t(error)}</AlertDescription></Alert>}
    <Section title={t("coverage")}>
      <p className="m-0 text-sm text-muted-foreground">{t("coverageHint")}</p>
      <Table scrollLabel={t("coverage")} className="min-w-[640px]">
        <TableHeader><TableRow><TableHead>{t("dataset")}</TableHead><TableHead>{t("availableRange")}</TableHead><TableHead>{t("researchAvailability")}</TableHead></TableRow></TableHeader>
        <TableBody>{rows.map(row => <TableRow key={row.id}>
          <TableCell className="max-w-80 whitespace-normal"><h3 className="m-0 text-sm font-medium">{t(`${row.id}Title`)}</h3><p className="m-0 text-sm text-muted-foreground">{row.description}</p></TableCell>
          <TableCell>{row.coverage ? `${row.coverage.start} — ${row.coverage.end}` : t("noCoverage")}</TableCell>
          <TableCell className="max-w-80 whitespace-normal"><Badge variant={row.state === "ready" ? "default" : "outline"}>{t(row.state === "ready" ? "available" : row.state === "not_ready" ? "notAvailable" : "limitedCoverage")}</Badge>
            {row.state !== "ready" && row.families.length > 0 && <p className="mb-0 text-xs text-muted-foreground">
              {row.families.filter(family => family.readiness !== "ready").map(family =>
                t("familyAvailability", { available: family.available_field_ids.length, total: family.supported_field_ids.length }) + (family.coverage_end ? t("through", { date: family.coverage_end }) : "")).join("; ")}.{" "}
              {row.id === "financial" && financial && <>{t("financialPending", { pending: financial.pending_instrument_count, gaps: financial.discovery_gap_count })}{" "}{financial.earliest_unresolved_date && t("earliestGap", { date: financial.earliest_unresolved_date })}{" "}{t("incompleteValues")}</>}
            </p>}
          </TableCell>
        </TableRow>)}</TableBody>
      </Table>
      <p className="m-0 text-xs text-muted-foreground">{overview.data_through_session ? t("dataThrough", { date: overview.data_through_session }) : t("noDataDate")} {t("availabilityVaries")}</p>
    </Section>
    <ResearchFieldCatalog catalog={catalog} />
    <CommonInputCatalog catalog={catalog} />
  </PageContent></Page>;
}

function CommonInputCatalog({ catalog }: { catalog: AlphaCatalog }) {
  const { t } = useTranslation("data");
  const inputs = catalog.builtins.filter((builtin) => builtin.result_type === "common_series");
  if (inputs.length === 0) return null;
  return <Disclosure title={<>{t("commonInputs")} · {t("expressions", { total: inputs.length })}</>}>
    <p>{t("commonInputHint")}</p>
    <Table scrollLabel={t("commonExpressions")} className="min-w-[640px]">
      <TableCaption className="sr-only">{t("commonExpressions")}</TableCaption>
      <TableHeader><TableRow><TableHead>{t("expression")}</TableHead><TableHead>{t("meaning")}</TableHead><TableHead>{t("missingValues")}</TableHead></TableRow></TableHeader>
      <TableBody>{inputs.map(input => <TableRow key={input.identifier}>
        <TableCell><code>{input.identifier}({input.parameters.map(parameter => parameter.name).join(", ")})</code></TableCell>
        <TableCell className="whitespace-normal">{builtinDisplay(input.identifier).description}<p className="m-0 text-xs text-muted-foreground">{input.examples.join(" · ")}</p></TableCell>
        <TableCell className="whitespace-normal">{builtinDisplay(input.identifier).missing}</TableCell>
      </TableRow>)}</TableBody>
    </Table>
    <Disclosure title={t("industryParameters", { total: catalog.industries.length })}>
      <p>{t("industryHint")}</p>
      <ul>{catalog.industries.map(industry => <li key={industry.code}><code>{industry.code}</code> {catalogLabel("industries", industry.code)}</li>)}</ul>
    </Disclosure>
  </Disclosure>;
}

function categoryReadiness(families: FieldFamilyAvailability[]): FieldFamilyAvailability["readiness"] {
  if (!families.some((family) => family.available_field_ids.length > 0)) return "not_ready";
  if (families.some((family) => family.readiness === "partial" || family.readiness === "not_ready")) return "partial";
  if (families.some((family) => family.readiness === "ready_with_gaps")) return "ready_with_gaps";
  if (families.some((family) => family.readiness === "ready_with_pending")) return "ready_with_pending";
  return "ready";
}

const PAGE_SIZE = 25;

export function ResearchFieldCatalog({ catalog }: { catalog: AlphaCatalog }) {
  const { t } = useTranslation("data");
  const [search, setSearch] = useState("");
  const searchInput = useRef<HTMLInputElement>(null);
  const [category, setCategory] = useState("");
  const [purpose, setPurpose] = useState("");
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const visible = catalog.fields.filter((field) => (
    (!category || field.research_category === category) &&
    matchesResearchField(field, search) &&
    (!purpose || field.research_purpose === purpose)
  ));
  const pageCount = Math.max(1, Math.ceil(visible.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const pageFields = visible.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);
  const selected = pageFields.find((field) => field.field_id === selectedId) ?? pageFields[0];
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [narrow, setNarrow] = useState(false);
  const catalogContainer = useRef<HTMLDivElement>(null);
  const [copyErrorFor, setCopyErrorFor] = useState<string | null>(null);
  useEffect(() => {
    const element = catalogContainer.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setNarrow(entry.contentRect.width < 960));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  async function copy(value: string) {
    try { await navigator.clipboard.writeText(value); setCopyErrorFor(current => current === selected?.field_id ? null : current); toast.add({ title: <CopyConfirmation />, type: "success" }); }
    catch { setCopyErrorFor(selected?.field_id ?? null); }
  }
  const selectedTrigger = useRef<HTMLButtonElement | null>(null);
  const closeLabel = t("closeDetails");
  function selectField(field: AlphaCatalogField) {
    setSelectedId(field.field_id);
    setDetailsOpen(true);
    setCopyErrorFor(null);
  }
  return <div ref={catalogContainer} className="min-w-0"><Section title={<>{t("researchFields")} <span className="text-sm font-normal text-muted-foreground">{t("fieldCount", { total: catalog.fields.length })}</span></>}>
    <FieldGroup>
      <Field>
        <FieldLabel className="sr-only" htmlFor="data-field-search">{t("searchFields")}</FieldLabel>
        <InputGroup>
          <InputGroupAddon><MagnifyingGlass aria-hidden="true" /></InputGroupAddon>
          <InputGroupInput id="data-field-search" ref={searchInput} value={search} role="searchbox" placeholder={t("searchPlaceholder")}
            onChange={event => { setSearch(event.target.value); setPage(1); }} />
          {search !== "" && <InputGroupAddon align="inline-end"><InputGroupButton aria-label={t("clearSearch")} size="icon-sm" onClick={() => { setSearch(""); setPage(1); searchInput.current?.focus(); }}><X aria-hidden="true" /></InputGroupButton></InputGroupAddon>}
        </InputGroup>
      </Field>
      <Field className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <ToggleGroup value={[category || "all"]} onValueChange={values => { if (values.length) { setCategory(values[0] === "all" ? "" : values[0]); setPage(1); } }} variant="outline" aria-label={t("category")} className="flex-wrap">
          {[{ value: "", label: t("allFields") }, { value: "market", label: t("market") }, { value: "financial", label: t("financial") }].map(item => <ToggleGroupItem key={item.value} value={item.value || "all"}>
            {item.label}{item.value ? ` ${catalog.fields.filter(field => field.research_category === item.value).length}` : ""}
          </ToggleGroupItem>)}
        </ToggleGroup>
        <Select value={purpose} onValueChange={value => { if (value !== null) { setPurpose(value); setPage(1); } }}>
          <SelectTrigger className="w-full lg:w-64" aria-label={t("purpose")}><SelectValue>{purpose ? catalogLabel("purposes", purpose) : t("allPurposes")}</SelectValue></SelectTrigger>
          <SelectContent><SelectGroup><SelectItem value="">{t("allPurposes")}</SelectItem>
            {[...new Set(catalog.fields.map(field => field.research_purpose))].sort(compareResearchPurposes).map(value => <SelectItem key={value} value={value}>{catalogLabel("purposes", value)}</SelectItem>)}
          </SelectGroup></SelectContent>
        </Select>
      </Field>
    </FieldGroup>
    {pageFields.length ? <div className={cn("grid min-w-0 gap-6", !narrow && "grid-cols-[minmax(0,1fr)_320px]")}>
      <div className="flex min-w-0 flex-col gap-4">
        <Table scrollLabel={t("researchFields")} className="min-w-[480px]">
          <TableCaption className="sr-only">{t("researchFields")}</TableCaption>
          <TableHeader><TableRow><TableHead>{t("field")}</TableHead><TableHead>{t("formulaName")}</TableHead><TableHead>{t("unit")}</TableHead></TableRow></TableHeader>
          <TableBody>{pageFields.map(field => <TableRow key={field.field_id} onClick={event => { if (!(event.target as HTMLElement).closest("button")) selectField(field); }} data-state={selected?.field_id === field.field_id ? "selected" : undefined}>
            <TableCell className="max-w-64 whitespace-normal"><Button variant="ghost" className="h-auto min-h-11 w-full justify-start whitespace-normal text-left" aria-pressed={selected?.field_id === field.field_id}
              ref={selected?.field_id === field.field_id ? selectedTrigger : undefined} onClick={() => selectField(field)}>
              {fieldDisplay(field.field_id).name}
            </Button></TableCell>
            <TableCell><code>{field.identifier}</code></TableCell><TableCell>{catalogLabel("units", field.unit)}</TableCell>
          </TableRow>)}</TableBody>
        </Table>
        <PageNavigation label={t("pages")} previousLabel={t("previous")} nextLabel={t("next")} previousDisabled={currentPage === 1} nextDisabled={currentPage === pageCount}
          onPrevious={() => setPage(currentPage - 1)} onNext={() => setPage(currentPage + 1)}>
          <span role="status">{t("showing", { start: (currentPage - 1) * PAGE_SIZE + 1, end: Math.min(currentPage * PAGE_SIZE, visible.length), total: visible.length })}</span><span>{currentPage} / {pageCount}</span>
        </PageNavigation>
      </div>
      {selected && !narrow && <aside className="min-w-0 rounded-lg border border-border bg-card p-4" aria-label={t("details")}><FieldDetail field={selected} copyError={copyErrorFor === selected.field_id} onCopy={copy} /></aside>}
    </div> : <Empty><EmptyHeader><EmptyTitle>{t(catalog.fields.length ? "noMatches" : "noFields")}</EmptyTitle></EmptyHeader></Empty>}
    <Sheet open={narrow && detailsOpen && !!selected} onOpenChange={setDetailsOpen}>
      <SheetContent showCloseButton={false} className="w-[min(100%,440px)] max-w-full overflow-y-auto p-4 sm:max-w-[440px]" finalFocus={() => selectedTrigger.current?.isConnected ? selectedTrigger.current : searchInput.current}>
        <SheetHeader className="p-0"><SheetTitle>{t("details")}</SheetTitle></SheetHeader>
        <SheetClose render={<Button variant="outline" className="self-start" />}>{closeLabel}</SheetClose>
        {selected && <FieldDetail field={selected} copyError={copyErrorFor === selected.field_id} onCopy={copy} />}
      </SheetContent>
    </Sheet>
  </Section></div>;
}

function FieldDetail({ field, copyError, onCopy }: { field: AlphaCatalogField; copyError: boolean; onCopy: (value: string) => Promise<void> }) {
  const { t } = useTranslation("data");
  const display = fieldDisplay(field.field_id);
  return <div className="flex min-w-0 flex-col gap-4 [overflow-wrap:anywhere]">
    <h3 className="m-0 text-base font-semibold">{display.name}</h3>
    <div className="flex min-w-0 items-start justify-between gap-2"><code className="min-w-0">{field.identifier}</code><Button variant="outline" size="icon" aria-label={t("copyFormula")} onClick={() => void onCopy(field.identifier)}><Copy aria-hidden="true" /></Button></div>
    <p className="m-0 text-sm">{display.description}</p>
    <dl className="m-0 grid gap-4 text-sm">
      <div><dt className="text-xs text-muted-foreground">{t("unit")}</dt><dd className="m-0">{catalogLabel("units", field.unit)}</dd></div>
      <div><dt className="text-xs text-muted-foreground">{t("period")}</dt><dd className="m-0">{catalogLabel("reportPeriods", field.report_period_selection)}</dd></div>
      <div><dt className="text-xs text-muted-foreground">{t("availableAt")}</dt><dd className="m-0">{catalogLabel("availability", field.availability)}</dd></div>
      <div><dt className="text-xs text-muted-foreground">{t("missingValues")}</dt><dd className="m-0">{catalogLabel("missingness", field.missingness)}</dd></div>
      <div><dt className="text-xs text-muted-foreground">{t("appliesTo")}</dt><dd className="m-0">{field.applicable_company_types.length ? t("companyTypes", { types: field.applicable_company_types.join(", ") }) : t("allInstruments")}</dd></div>
    </dl>
    {field.example && <div><p className="text-xs text-muted-foreground">{t("example")}</p><div className="flex min-w-0 items-start justify-between gap-2"><code className="min-w-0">{field.example}</code><Button variant="outline" size="icon" aria-label={t("copyExample")} onClick={() => void onCopy(field.example)}><Copy aria-hidden="true" /></Button></div></div>}
    {copyError && <Alert variant="destructive"><AlertDescription>{t("copyUnavailable")}</AlertDescription></Alert>}
  </div>;
}

function CopyConfirmation() { const { t } = useTranslation("data"); return <>{t("copied")}</>; }

export function DataPage() {
  const { t } = useTranslation("data");
  const [resources, setResources] = useState<DataPageResources | null>(null);
  const [error, setError] = useState<"unavailable" | null>(null);

  const [refreshing, setRefreshing] = useState(false);
  const refreshingRef = useRef(false);
  const refresh = useCallback(async () => {
    if (refreshingRef.current) return;
    refreshingRef.current = true;
    setRefreshing(true);
    const result = await loadDataPage();
    if (result.resources !== null) setResources(result.resources);
    setError(result.error);
    refreshingRef.current = false;
    setRefreshing(false);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (!resources) return <Page className="px-4 py-6 sm:px-6 lg:px-8" aria-label={t("title")}><PageContent>
    <PageHeader title={t("title")} />
    {error ? <Alert variant="destructive"><AlertDescription>{t(error)}<Button variant="outline" disabled={refreshing} onClick={() => void refresh()}>{t("retry")}</Button></AlertDescription></Alert> : <p role="status">{t("loading")}</p>}
  </PageContent></Page>;
  return <DataOverviewView catalog={resources.catalog} overview={resources.overview} error={error} refreshing={refreshing} onRefresh={() => void refresh()} />;
}
