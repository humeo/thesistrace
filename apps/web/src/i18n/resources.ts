import { commonEn, commonZh } from "./messages/common";
import { navigationEn, navigationZh } from "./messages/navigation";
import { copy } from "./messages/landing";
import { authEn, authZh } from "./messages/auth";

export const resources = {
  en: { common: commonEn, navigation: navigationEn, auth: authEn, landing: { page: copy.en } },
  "zh-CN": { common: commonZh, navigation: navigationZh, auth: authZh, landing: { page: copy.zh } },
} as const;
