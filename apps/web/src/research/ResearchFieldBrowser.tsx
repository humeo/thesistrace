import { useState } from "react";

import type { AlphaCatalog } from "../alphaCatalog";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { useTranslation } from "../i18n";
import { fieldDisplay, matchesResearchField } from "../i18n/catalog";

export function ResearchFieldBrowser({ catalog, onInsert }: {
  catalog: AlphaCatalog;
  onInsert: (identifier: string) => void;
}) {
  const { t } = useTranslation("research");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const visible = catalog.fields.filter((field) => matchesResearchField(field, query));
  const selected = visible.find((field) => field.field_id === selectedId) ?? visible[0];

  return (
    <div className="grid min-h-0 gap-4">
      <label className="grid gap-2 text-sm font-medium" htmlFor="research-field-search">
        {t("searchFields")}
        <Input id="research-field-search" role="searchbox" value={query}
          onChange={(event) => setQuery(event.target.value)} placeholder={t("searchFieldsPlaceholder")} />
      </label>
      <div className="grid max-h-[45dvh] min-h-0 gap-1 overflow-y-auto" role="group" aria-label={t("browseFields")}>
        {visible.map((field) => (
          <Button key={field.field_id} id={`research-field-${field.field_id}`} type="button" variant="ghost"
            aria-pressed={selected?.field_id === field.field_id}
            className="grid min-h-11 w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-md px-3 py-2 text-left text-sm text-foreground hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring aria-pressed:bg-muted"
            onClick={() => setSelectedId(field.field_id)}
            onDoubleClick={() => onInsert(field.identifier)}>
            <span className="truncate">{fieldDisplay(field.field_id).name}</span>
            <code className="truncate text-xs text-muted-foreground">{field.identifier}</code>
          </Button>
        ))}
        {visible.length === 0 ? <p className="py-4 text-sm text-muted-foreground">{t("noFieldsFound")}</p> : null}
      </div>
      {selected ? (
        <section aria-label={t("fieldDetails")} className="grid gap-3 border-t border-border pt-4 text-sm">
          <div className="grid gap-1">
            <h3 className="m-0 text-base font-semibold">{fieldDisplay(selected.field_id).name}</h3>
            <code className="text-xs text-muted-foreground">{selected.identifier}</code>
          </div>
          <p className="m-0 text-muted-foreground">{fieldDisplay(selected.field_id).description}</p>
          <Button type="button" onClick={() => onInsert(selected.identifier)}>{t("insertField")}</Button>
        </section>
      ) : null}
    </div>
  );
}
