import { commonEn, commonZh } from "./messages/common";
import { navigationEn, navigationZh } from "./messages/navigation";
import { copy } from "./messages/landing";
import { authEn, authZh } from "./messages/auth";
import { dataEn, dataZh } from "./messages/data";
import fields from "./messages/catalog-fields.json";
import catalog from "./messages/catalog-meta.json";
import { editorEn, editorZh } from "./messages/editor";
import { diagnosticsEn, diagnosticsZh } from "./messages/diagnostics";

export const resources = {
  en: { common: commonEn, navigation: navigationEn, auth: authEn, landing: { page: copy.en }, data: dataEn, editor: editorEn, diagnostics: diagnosticsEn, catalog: { fields: fields.en, ...catalog.en } },
  "zh-CN": { common: commonZh, navigation: navigationZh, auth: authZh, landing: { page: copy.zh }, data: dataZh, editor: editorZh, diagnostics: diagnosticsZh, catalog: { fields: fields["zh-CN"], ...catalog["zh-CN"] } },
} as const;
