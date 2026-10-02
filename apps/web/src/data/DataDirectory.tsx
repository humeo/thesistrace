import { cn } from "cn";
import { Copy, MagnifyingGlass, X } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import { useUrlSelection } from "../shell/useUrlSelection";

import type { AlphaCatalog, AlphaCatalogField } from "../alphaCatalog";
import { Disclosure } from "../components/layout/Disclosure";
import { Alert, AlertDescription } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Empty, EmptyHeader, EmptyTitle } from "../components/ui/empty";
import { Field, FieldLabel } from "../components/ui/field";
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from "../components/ui/input-group";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Separator } from "../components/ui/separator";
import { Sheet, SheetClose, SheetContent, SheetHeader, SheetTitle } from "../components/ui/sheet";
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { toast } from "../components/ui/toast";
import { ToggleGroup, ToggleGroupItem } from "../components/ui/toggle-group";
import { useTranslation } from "../i18n";
import { builtinDisplay, catalogLabel, compareResearchPurposes, fieldDisplay, matchesResearchField } from "../i18n/catalog";

type CommonInput = AlphaCatalog["builtins"][number];
const directoryTabs = ["fields", "functions", "industries"] as const;

export function DataDirectory({ catalog }: { catalog: AlphaCatalog }) {
  const { t } = useTranslation("data");
  const [tab, setTab] = useUrlSelection("tab", directoryTabs, "fields");
  const inputs = catalog.builtins.filter(input => input.result_type === "common_series");
  return <section className="data-directory min-w-0" aria-label={t("directory")}>
    <Tabs value={tab} onValueChange={setTab}>
      <TabsList variant="line" className="data-directory-tabs w-full justify-start border-b border-border p-0" aria-label={t("directory")}>
        <TabsTrigger value="fields">{t("fieldsTab")}<span className="data-directory-count">{catalog.fields.length}</span></TabsTrigger>
        <TabsTrigger value="functions">{t("functionsTab")}<span className="data-directory-count">{inputs.length}</span></TabsTrigger>
        <TabsTrigger value="industries">{t("industriesTab")}<span className="data-directory-count">{catalog.industries.length}</span></TabsTrigger>
      </TabsList>
      <TabsContent value="fields" className="pt-4">{tab === "fields" && <ResearchFieldCatalog catalog={catalog} embedded />}</TabsContent>
      <TabsContent value="functions" className="pt-4">{tab === "functions" && <CommonInputCatalog catalog={catalog} inputs={inputs} />}</TabsContent>
      <TabsContent value="industries" className="pt-4">{tab === "industries" && <IndustryCatalog catalog={catalog} />}</TabsContent>
    </Tabs>
  </section>;
}

function CatalogSearch({ id, label, placeholder, value, onChange, inputRef }: {
  id: string; label: string; placeholder: string; value: string; onChange: (value: string) => void;
  inputRef?: React.RefObject<HTMLInputElement | null>;
}) {
  const { t } = useTranslation("data");
  return <Field className="w-90 max-w-full shrink-0">
    <FieldLabel className="sr-only" htmlFor={id}>{label}</FieldLabel>
    <InputGroup>
      <InputGroupInput id={id} ref={inputRef} role="searchbox" value={value} placeholder={placeholder} onChange={event => onChange(event.target.value)} />
      <InputGroupAddon><MagnifyingGlass aria-hidden="true" /></InputGroupAddon>
      {value && <InputGroupAddon align="inline-end"><InputGroupButton aria-label={t("clearSearch")} size="icon-sm" onClick={() => { onChange(""); inputRef?.current?.focus(); }}><X aria-hidden="true" /></InputGroupButton></InputGroupAddon>}
    </InputGroup>
  </Field>;
}

export function ResearchFieldCatalog({ catalog, embedded = false }: { catalog: AlphaCatalog; embedded?: boolean }) {
  const { t } = useTranslation("data");
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [purpose, setPurpose] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [narrow, setNarrow] = useState(true);
  const [copyError, setCopyError] = useState(false);
  const catalogContainer = useRef<HTMLDivElement>(null);
  const searchInput = useRef<HTMLInputElement>(null);
  const selectedTrigger = useRef<HTMLButtonElement>(null);
  const visible = catalog.fields.filter(field =>
    (!category || field.research_category === category) && matchesResearchField(field, search) &&
    (!purpose || field.research_purpose === purpose));
  const selected = visible.find(field => field.field_id === selectedId) ?? visible[0];

  useEffect(() => {
    const element = catalogContainer.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setNarrow(entry.contentRect.width < 1024));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  async function copy(value: string) {
    try { await navigator.clipboard.writeText(value); setCopyError(false); toast.add({ title: t("copied"), type: "success" }); }
    catch { setCopyError(true); }
  }
  function selectField(field: AlphaCatalogField, trigger: HTMLButtonElement) {
    selectedTrigger.current = trigger;
    setSelectedId(field.field_id);
    setCopyError(false);
    if (narrow) setDetailsOpen(true);
  }
  return <div ref={catalogContainer} className="min-w-0">
    {!embedded && <h2 className="mb-4 text-base font-semibold">{t("researchFields")} <span className="text-sm font-normal text-muted-foreground">{catalog.fields.length}</span></h2>}
    <div className="mb-4 flex min-w-0 flex-wrap items-center gap-2">
      <CatalogSearch id="data-field-search" label={t("searchFields")} placeholder={t("searchPlaceholder")} value={search} onChange={setSearch} inputRef={searchInput} />
      <ToggleGroup value={[category || "all"]} onValueChange={values => { if (values.length) setCategory(values[0] === "all" ? "" : values[0]); }} variant="outline" aria-label={t("category")} className="flex-wrap">
        {[{ value: "", label: t("allFields") }, { value: "market", label: t("market") }, { value: "financial", label: t("financial") }].map(item => <ToggleGroupItem key={item.value} value={item.value || "all"}>
          {item.label}{item.value ? ` ${catalog.fields.filter(field => field.research_category === item.value).length}` : ""}
        </ToggleGroupItem>)}
      </ToggleGroup>
      <Select value={purpose} onValueChange={value => { if (value !== null) setPurpose(value); }}>
        <SelectTrigger className="w-36" aria-label={t("purpose")}><SelectValue>{purpose ? catalogLabel("purposes", purpose) : t("allPurposes")}</SelectValue></SelectTrigger>
        <SelectContent className="console-workspace"><SelectGroup><SelectItem value="">{t("allPurposes")}</SelectItem>
          {[...new Set(catalog.fields.map(field => field.research_purpose))].sort(compareResearchPurposes).map(value => <SelectItem key={value} value={value}>{catalogLabel("purposes", value)}</SelectItem>)}
        </SelectGroup></SelectContent>
      </Select>
      <span className="ml-auto text-sm text-muted-foreground" role="status">{t("matchingFields", { total: visible.length })}</span>
    </div>
    {visible.length ? <div className={cn("data-directory-split min-w-0 overflow-hidden rounded-xl border border-border bg-card", !narrow && "grid grid-cols-[minmax(0,1fr)_320px]")}>
      <Table density="catalog" scrollLabel={t("researchFields")} className="data-field-table min-w-[480px]">
        <TableCaption className="sr-only">{t("researchFields")}</TableCaption>
        <TableHeader><TableRow><TableHead>{t("field")}</TableHead><TableHead>{t("identifier")}</TableHead><TableHead>{t("unit")}</TableHead></TableRow></TableHeader>
        <TableBody>{visible.map(field => <TableRow key={field.field_id} data-state={selected?.field_id === field.field_id ? "selected" : undefined} onClick={event => {
          if (!(event.target as HTMLElement).closest("button")) {
            const trigger = event.currentTarget.querySelector("button");
            if (trigger) selectField(field, trigger);
          }
        }}>
          <TableCell className="max-w-64 whitespace-normal"><Button variant="ghost" className="h-auto min-h-9 w-full justify-start whitespace-normal text-left" aria-pressed={selected?.field_id === field.field_id} onClick={event => selectField(field, event.currentTarget)}>{fieldDisplay(field.field_id).name}</Button></TableCell>
          <TableCell><code>{field.identifier}</code></TableCell><TableCell>{catalogLabel("units", field.unit)}</TableCell>
        </TableRow>)}</TableBody>
      </Table>
      {selected && !narrow && <aside className="data-directory-detail min-w-0 border-l border-border p-5" aria-label={t("details")}><FieldDetail field={selected} copyError={copyError} onCopy={copy} /></aside>}
    </div> : <Empty><EmptyHeader><EmptyTitle>{t(catalog.fields.length ? "noMatches" : "noFields")}</EmptyTitle></EmptyHeader></Empty>}
    <Sheet open={narrow && detailsOpen && !!selected} onOpenChange={setDetailsOpen}>
      <SheetContent showCloseButton={false} className="w-[min(100%,440px)] max-w-full overflow-y-auto p-4 sm:max-w-[440px]" finalFocus={() => selectedTrigger.current?.isConnected ? selectedTrigger.current : searchInput.current}>
        <SheetHeader className="p-0"><SheetTitle>{t("details")}</SheetTitle></SheetHeader>
        <SheetClose render={<Button variant="outline" className="self-start" />}>{t("closeDetails")}</SheetClose>
        {selected && <FieldDetail field={selected} copyError={copyError} onCopy={copy} />}
      </SheetContent>
    </Sheet>
  </div>;
}

function FieldDetail({ field, copyError, onCopy }: { field: AlphaCatalogField; copyError: boolean; onCopy: (value: string) => Promise<void> }) {
  const { t } = useTranslation("data");
  const display = fieldDisplay(field.field_id);
  return <div className="flex min-w-0 flex-col gap-4 text-sm [overflow-wrap:anywhere]">
    <h3 className="m-0 text-base font-semibold">{display.name}</h3>
    <div className="flex min-w-0 items-center justify-between gap-2 rounded-md bg-muted/50 px-3 py-2"><code className="min-w-0">{field.identifier}</code><Button variant="ghost" size="icon-sm" aria-label={t("copyFormula")} onClick={() => void onCopy(field.identifier)}><Copy aria-hidden="true" /></Button></div>
    <p className="m-0 text-muted-foreground">{display.description}</p>
    <dl className="data-detail-facts m-0 grid gap-x-3 gap-y-2 border-y border-border py-4 text-sm">
      <dt>{t("unit")}</dt><dd>{catalogLabel("units", field.unit)}</dd>
      <dt>{t("period")}</dt><dd>{catalogLabel("reportPeriods", field.report_period_selection)}</dd>
      <dt>{t("availableAt")}</dt><dd>{catalogLabel("availability", field.availability)}</dd>
      <dt>{t("missingValues")}</dt><dd>{catalogLabel("missingness", field.missingness)}</dd>
    </dl>
    {field.applicable_company_types.length > 0 && <p className="m-0 text-sm text-muted-foreground">{t("appliesTo")}: {t("companyTypes", { types: field.applicable_company_types.join(", ") })}</p>}
    {field.example && <Disclosure variant="row" title={t("example")}><div className="flex items-center justify-between gap-2"><code>{field.example}</code><Button variant="ghost" size="icon-sm" aria-label={t("copyExample")} onClick={() => void onCopy(field.example)}><Copy aria-hidden="true" /></Button></div></Disclosure>}
    {copyError && <Alert variant="destructive"><AlertDescription>{t("copyUnavailable")}</AlertDescription></Alert>}
  </div>;
}

function inputName(identifier: string, t: ReturnType<typeof useTranslation<"data">>["t"]) {
  switch (identifier) {
    case "universe_return": return t("universeReturn");
    case "universe_advancing_fraction": return t("universeAdvancingFraction");
    case "industry_return": return t("industryReturn");
    case "industry_advancing_fraction": return t("industryAdvancingFraction");
    default: return identifier;
  }
}

function signature(input: CommonInput, industryCode?: number) {
  return `${input.identifier}(${input.parameters.map(parameter => industryCode ?? parameter.name).join(", ")})`;
}

function CommonInputCatalog({ catalog, inputs }: { catalog: AlphaCatalog; inputs: CommonInput[] }) {
  const { t } = useTranslation("data");
  const [search, setSearch] = useState("");
  const searchInput = useRef<HTMLInputElement>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [copyError, setCopyError] = useState(false);
  const visible = inputs.filter(input => [input.identifier, builtinDisplay(input.identifier, "en").description, builtinDisplay(input.identifier, "zh-CN").description,
    inputName(input.identifier, t)].some(value => value.toLowerCase().includes(search.trim().toLowerCase())));
  const selected = visible.find(input => input.identifier === selectedId) ?? visible[0];
  async function copy(value: string) {
    try { await navigator.clipboard.writeText(value); setCopyError(false); toast.add({ title: t("copied"), type: "success" }); }
    catch { setCopyError(true); }
  }
  return <div className="min-w-0">
    <div className="mb-4 flex flex-wrap items-center gap-3"><CatalogSearch id="data-function-search" label={t("searchFunctions")} placeholder={t("functionSearchPlaceholder")} value={search} onChange={setSearch} inputRef={searchInput} />
      <span className="text-sm text-muted-foreground" role="status">{t("matchingFunctions", { total: visible.length })}</span></div>
    {visible.length ? <div className="data-function-split min-w-0 overflow-hidden rounded-xl border border-border bg-card">
      <div role="group" aria-label={t("functionsTab")} className="flex min-w-0 flex-col self-start divide-y divide-border">{visible.map(input => <Button key={input.identifier} variant="ghost" size="sm" className="data-function-row h-auto min-h-20 w-full flex-col items-start gap-1 rounded-none px-4 py-3 text-left whitespace-normal" aria-pressed={selected?.identifier === input.identifier} onClick={() => { setSelectedId(input.identifier); setCopyError(false); }}>
        <span>{inputName(input.identifier, t)}</span><code className="w-full break-all">{signature(input)}</code>
      </Button>)}</div>
      {selected && <aside className="data-function-detail flex min-w-0 flex-col gap-5 p-6" aria-label={t("functionDetails")}>
        <div className="flex min-w-0 flex-col gap-2">
          <h3 className="m-0 text-base leading-6 font-semibold">{inputName(selected.identifier, t)}</h3>
          <p className="m-0 text-sm text-muted-foreground">{builtinDisplay(selected.identifier).description}</p>
        </div>
        <div className="flex items-center justify-between gap-2 rounded-md bg-muted/50 px-3 py-2"><code className="min-w-0 break-all text-sm">{signature(selected)}</code><Button variant="ghost" size="icon-sm" aria-label={t("copyExpression")} onClick={() => void copy(signature(selected))}><Copy aria-hidden="true" /></Button></div>
        <Separator />
        <dl className="data-detail-facts data-function-facts m-0 grid gap-x-4 gap-y-3 text-sm">
          <dt>{t("scope")}</dt><dd>{selected.parameters.length ? t("industrySubset") : t("selectedUniverse")}</dd>
          <dt>{t("parameters")}</dt><dd>{selected.parameters.length ? <code>{selected.parameters.map(parameter => parameter.name).join(", ")}</code> : t("none")}</dd>
          <dt>{t("returnValue")}</dt><dd>{selected.identifier.endsWith("advancing_fraction") ? t("fractionReturn") : t("returnSeries")}</dd>
          <dt>{t("missingValues")}</dt><dd>{builtinDisplay(selected.identifier).missing}</dd>
        </dl>
        {copyError && <Alert variant="destructive"><AlertDescription>{t("copyUnavailable")}</AlertDescription></Alert>}
        <div className="-mx-6 -mb-6 border-t border-border">
          <Disclosure variant="row" title={t("calculationNotes")} defaultOpen>
            <div className="flex flex-col gap-3 text-muted-foreground"><p className="m-0">{t("commonInputHint")}</p><p className="m-0">{builtinDisplay(selected.identifier).numeric}</p></div>
          </Disclosure>
          <Disclosure variant="row" title={t("example")} defaultOpen><code>{signature(selected, selected.parameters.length ? catalog.industries[0]?.code : undefined)}</code></Disclosure>
        </div>
      </aside>}
    </div> : <Empty><EmptyHeader><EmptyTitle>{t("noFunctions")}</EmptyTitle></EmptyHeader></Empty>}
  </div>;
}

function IndustryCatalog({ catalog }: { catalog: AlphaCatalog }) {
  const { t } = useTranslation("data");
  const [search, setSearch] = useState("");
  const searchInput = useRef<HTMLInputElement>(null);
  const [copyError, setCopyError] = useState(false);
  const visible = [...catalog.industries].sort((a, b) => a.code - b.code).filter(industry =>
    [String(industry.code), catalogLabel("industries", industry.code, "en"), catalogLabel("industries", industry.code, "zh-CN")]
      .some(value => value.toLowerCase().includes(search.trim().toLowerCase())));
  async function copy(value: string) {
    try { await navigator.clipboard.writeText(value); setCopyError(false); toast.add({ title: t("copied"), type: "success" }); }
    catch { setCopyError(true); }
  }
  return <div className="min-w-0">
    <div className="mb-4 flex flex-wrap items-center gap-3"><CatalogSearch id="data-industry-search" label={t("searchIndustries")} placeholder={t("industrySearchPlaceholder")} value={search} onChange={setSearch} inputRef={searchInput} />
      <span className="text-sm text-muted-foreground" role="status">{t("matchingIndustries", { total: visible.length })}</span></div>
    {visible.length ? <div className="data-industry-grid rounded-xl border border-border bg-card p-4" role="list">
      {visible.map(industry => <div key={industry.code} role="listitem" className="data-industry-row flex min-w-0 items-center gap-3 border-b border-border px-2 text-sm">
        <span className="min-w-0 flex-1 truncate">{catalogLabel("industries", industry.code)}</span><code className="text-sm text-muted-foreground">{industry.code}</code>
        <Button variant="ghost" size="icon-xs" aria-label={t("copyIndustryCode", { code: industry.code })} onClick={() => void copy(String(industry.code))}><Copy aria-hidden="true" /></Button>
      </div>)}
    </div> : <Empty><EmptyHeader><EmptyTitle>{t("noIndustries")}</EmptyTitle></EmptyHeader></Empty>}
    {copyError && <Alert variant="destructive"><AlertDescription>{t("copyUnavailable")}</AlertDescription></Alert>}
  </div>;
}
