import { useEffect, useId, useState } from "react";
import { useTranslation } from "../i18n";
import { Disclosure } from "../components/layout/Disclosure";
import { Alert, AlertDescription } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Field, FieldGroup, FieldLabel } from "../components/ui/field";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Skeleton } from "../components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "../components/ui/toggle-group";
import { authoringTopics, loadAuthoringReference, type AuthoringReference as Reference, type AuthoringTopic } from "./api";
import { CopyButton } from "./CopyButton";

export function AuthoringReference() {
  const { t } = useTranslation("mcp");
  const memberId = useId();
  const [query, setQuery] = useState<{ topic: AuthoringTopic; symbol: string | null }>({ topic: "workflow", symbol: null });
  const [reference, setReference] = useState<Reference | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setFailed(false);
    setReference(current => current?.topic === query.topic ? current : null);
    void loadAuthoringReference(query.topic, query.symbol, controller.signal).then(result => {
      if (!controller.signal.aborted) setReference(current => ({
        ...result, symbols: result.entry ? current?.symbols ?? [] : result.symbols,
      }));
    }).catch(() => { if (!controller.signal.aborted) setFailed(true); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [query, revision]);
  const entry = !loading && !failed ? reference?.entry : null;
  return <div className="flex min-w-0 flex-col gap-4" aria-label={t("reference.title")}>
    <p className="m-0 text-sm text-muted-foreground">{t("reference.shared")}</p>
    <ToggleGroup value={[query.topic]} onValueChange={values => {
      if (values[0] && values[0] !== query.topic) setQuery({ topic: values[0] as AuthoringTopic, symbol: null });
    }} aria-label={t("reference.topics")} className="flex-wrap self-start">
      {authoringTopics.map(topic => <ToggleGroupItem key={topic} value={topic}>{t(`reference.topic.${topic}`)}</ToggleGroupItem>)}
    </ToggleGroup>
    {reference ? <FieldGroup><Field>
      <FieldLabel htmlFor={memberId}>{t("reference.member")}</FieldLabel>
      <Select value={query.symbol ?? "__index__"} onValueChange={value => {
        if (value !== null) setQuery(current => ({ ...current, symbol: value === "__index__" ? null : value }));
      }}>
        <SelectTrigger id={memberId} aria-label={t("reference.member")} className="w-full"><SelectValue>{query.symbol ?? t("reference.overview")}</SelectValue></SelectTrigger>
        <SelectContent><SelectGroup>
          <SelectItem value="__index__">{t("reference.overview")}</SelectItem>
          {reference.symbols.map(item => <SelectItem key={item.symbol} value={item.symbol}>{item.symbol}</SelectItem>)}
        </SelectGroup></SelectContent>
      </Select>
    </Field></FieldGroup> : null}
    {loading ? <Skeleton className="h-24 w-full" aria-label={t("reference.loading")} /> : null}
    {failed ? <Alert variant="destructive"><AlertDescription>{t("reference.failed")}</AlertDescription><Button variant="outline" onClick={() => setRevision(value => value + 1)}>{t("retry")}</Button></Alert> : null}
    {!loading && !failed && reference ? <>
      {!reference.found ? <Alert><AlertDescription>{t("reference.notFound")}</AlertDescription></Alert> : null}
      {entry ? <>
        <h3 className="m-0 text-base font-medium"><code>{entry.symbol}</code></h3>
        <p className="m-0">{entry.description}</p>
        {entry.signature ? <ReferenceCode source={entry.signature} /> : null}
        {Object.keys(entry.parameters).length ? <Table scrollLabel={t("reference.parameters")}>
          <TableHeader><TableRow><TableHead>{t("reference.parameter")}</TableHead><TableHead>{t("reference.meaning")}</TableHead></TableRow></TableHeader>
          <TableBody>{Object.entries(entry.parameters).map(([name, description]) => <TableRow key={name}><TableCell><code>{name}</code></TableCell><TableCell className="whitespace-normal">{description}</TableCell></TableRow>)}</TableBody>
        </Table> : null}
        {entry.returns ? <p className="m-0"><strong>{t("reference.returns")}</strong> {entry.returns}</p> : null}
        {entry.notes.map(note => <p className="m-0" key={note}>{note}</p>)}
        {entry.examples.map(example => <div key={example.title} className="flex min-w-0 flex-col gap-2">
          <div className="flex items-center justify-between gap-3"><span>{example.title}</span><CopyButton text={example.source} label={t("reference.copyExample")} /></div>
          <ReferenceCode source={example.source} />
        </div>)}
        {Object.keys(entry.constraints).length ? <Disclosure title={t("reference.constraints")}><ReferenceCode source={JSON.stringify(entry.constraints, null, 2)} /></Disclosure> : null}
        {entry.data_schema ? <Disclosure title={t("reference.objectFields")}><ReferenceCode source={JSON.stringify(entry.data_schema, null, 2)} /></Disclosure> : null}
      </> : <ol className="m-0 flex flex-col gap-3 pl-5">{reference.overview.map(note => <li key={note}>{note}</li>)}</ol>}
    </> : null}
  </div>;
}

function ReferenceCode({ source }: { source: string }) {
  return <pre tabIndex={0} className="m-0 max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-md border border-border bg-muted p-3 text-sm"><code>{source}</code></pre>;
}
