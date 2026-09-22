import type { AlphaCatalogField } from "../alphaCatalog";
import { interfaceLocale, type InterfaceLocale } from "./index";
import fields from "./messages/catalog-fields.json";
import metadata from "./messages/catalog-meta.json";

// Display only: Core owns allowed fields, units, calculation semantics and membership.
// The Core catalog coverage test requires every current identity, including unavailable fields.
function entry<T>(dictionary: Readonly<Record<string, T>>, id: string): T {
  const value = dictionary[id];
  if (value === undefined) throw new Error(`Missing catalog translation: ${id}`);
  return value;
}

export function fieldDisplay(fieldId: string, locale: InterfaceLocale = interfaceLocale()) {
  return entry(fields[locale], fieldId);
}

export function builtinDisplay(identifier: string, locale: InterfaceLocale = interfaceLocale()) {
  return entry(metadata[locale].builtins, identifier);
}

type LabelGroup = Exclude<keyof typeof metadata.en, "builtins">;
export function catalogLabel(group: LabelGroup, id: string | number, locale: InterfaceLocale = interfaceLocale()): string {
  return entry(metadata[locale][group], String(id));
}

/** Search both reviewed languages without coupling ordering or filters to the active locale. */
export function matchesResearchField(field: AlphaCatalogField, query: string): boolean {
  const en = fieldDisplay(field.field_id, "en");
  const zh = fieldDisplay(field.field_id, "zh-CN");
  return [field.identifier, field.display_name, field.description, en.name, en.description, zh.name, zh.description]
    .some((value) => value.toLowerCase().includes(query.trim().toLowerCase()));
}

export function compareResearchPurposes(a: string, b: string): number {
  return catalogLabel("purposes", a, "en").localeCompare(catalogLabel("purposes", b, "en"), "en");
}
