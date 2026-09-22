import { commonEn, commonZh } from "./messages/common";
import { navigationEn, navigationZh } from "./messages/navigation";
import { copy } from "./messages/landing";
import { authEn, authZh } from "./messages/auth";
import { dataEn, dataZh } from "./messages/data";
import fields from "./messages/catalog-fields.json";
import catalog from "./messages/catalog-meta.json";

export const resources = {
  en: { common: commonEn, navigation: navigationEn, auth: authEn, landing: { page: copy.en }, data: dataEn, catalog: { fields: fields.en, ...catalog.en } },
  "zh-CN": { common: commonZh, navigation: navigationZh, auth: authZh, landing: { page: copy.zh }, data: dataZh, catalog: { fields: fields["zh-CN"], ...catalog["zh-CN"] } },
} as const;
