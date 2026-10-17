import "i18next";
import type { resources } from "./resources";
import type { billingEn } from "./messages/billing";

declare module "i18next" {
  interface CustomTypeOptions {
    defaultNS: "common";
    resources: typeof resources.en & { billing: typeof billingEn };
    enableSelector: false;
    strictKeyChecks: true;
  }
}
