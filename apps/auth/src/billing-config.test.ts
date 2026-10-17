import { expect, it } from "vitest";
import { readBillingSettings } from "./billing-config.js";

it("requires a complete isolated or live merchant configuration before accepting payments", () => {
  expect(readBillingSettings({}, "development")).toEqual({ mode: "disabled" });
  const values = {
    THESISTRACE_CREEM_MODE: "test",
    CREEM_API_KEY: "fixture-api-key-for-creem",
    CREEM_WEBHOOK_SECRET: "fixture-webhook-secret-creem",
    THESISTRACE_CREEM_PRO_PRODUCT_ID: "prod_pro",
    THESISTRACE_CREEM_MAX_PRODUCT_ID: "prod_max",
  };
  expect(readBillingSettings(values, "test")).toMatchObject({
    mode: "test",
    apiOrigin: "https://test-api.creem.io",
    products: { pro: "prod_pro", max: "prod_max" },
  });
  for (const invalid of [
    { ...values, CREEM_WEBHOOK_SECRET: "" },
    { ...values, THESISTRACE_CREEM_MAX_PRODUCT_ID: "prod_pro" },
    {
      ...values,
      THESISTRACE_CREEM_MODE: "live",
      THESISTRACE_CREEM_API_ORIGIN: "http://attacker.test",
    },
    { CREEM_API_KEY: values.CREEM_API_KEY },
  ]) {
    expect(() => readBillingSettings(invalid, "production")).toThrow();
  }
});
