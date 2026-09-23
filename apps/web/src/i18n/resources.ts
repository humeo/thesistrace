import { dailyEn, dailyZh } from "./messages/daily";
import { batchesEn, batchesZh } from "./messages/batches";
import { runsEn, runsZh } from "./messages/runs";
import { analysisEn, analysisZh } from "./messages/analysis";
import { metricHelpEn, metricHelpZh } from "./messages/metric-help";
import { commonEn, commonZh } from "./messages/common";
import { navigationEn, navigationZh } from "./messages/navigation";
import { copy } from "./messages/landing";
import { authEn, authZh } from "./messages/auth";
import { dataEn, dataZh } from "./messages/data";
import fields from "./messages/catalog-fields.json";
import catalog from "./messages/catalog-meta.json";
import { editorEn, editorZh } from "./messages/editor";
import { researchEn, researchZh } from "./messages/research";
import { diagnosticsEn, diagnosticsZh } from "./messages/diagnostics";

export const resources = {
  en: { daily: dailyEn, runs: runsEn, batches: batchesEn, analysis: { ...analysisEn, metrics: metricHelpEn }, common: commonEn, navigation: navigationEn, auth: authEn, landing: { page: copy.en }, data: dataEn, editor: editorEn, diagnostics: diagnosticsEn, research: researchEn, catalog: { fields: fields.en, ...catalog.en } },
  "zh-CN": { daily: dailyZh, runs: runsZh, batches: batchesZh, analysis: { ...analysisZh, metrics: metricHelpZh }, common: commonZh, navigation: navigationZh, auth: authZh, landing: { page: copy.zh }, data: dataZh, editor: editorZh, diagnostics: diagnosticsZh, research: researchZh, catalog: { fields: fields["zh-CN"], ...catalog["zh-CN"] } },
} as const;
