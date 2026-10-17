import { z } from "zod";

export type EnabledBillingSettings = Readonly<{
  mode: "test" | "live";
  apiOrigin: string;
  apiKey: string;
  webhookSecret: string;
  products: Readonly<{ pro: string; max: string }>;
}>;
export type BillingSettings =
  Readonly<{ mode: "disabled" }> | EnabledBillingSettings;

export function readBillingSettings(
  environment: Record<string, string | undefined>,
  runtime: "production" | "development" | "test",
): BillingSettings {
  const mode = z
    .enum(["disabled", "test", "live"])
    .parse(environment.THESISTRACE_CREEM_MODE ?? "disabled");
  if (mode === "disabled") {
    if (
      [
        "CREEM_API_KEY",
        "CREEM_WEBHOOK_SECRET",
        "THESISTRACE_CREEM_PRO_PRODUCT_ID",
        "THESISTRACE_CREEM_MAX_PRODUCT_ID",
        "THESISTRACE_CREEM_API_ORIGIN",
      ].some((key) => Boolean(environment[key]))
    ) {
      throw new Error("Creem credentials require an explicit payment mode");
    }
    return { mode };
  }
  const required = (name: string, schema: z.ZodType<string>) => {
    const value = schema.safeParse(environment[name]);
    if (!value.success)
      throw new Error(`Invalid billing configuration: ${name}`);
    return value.data;
  };
  const credential = z.string().min(16).max(512).regex(/^\S+$/);
  const apiKey = required("CREEM_API_KEY", credential);
  const webhookSecret = required("CREEM_WEBHOOK_SECRET", credential);
  const product = z.string().regex(/^prod_[A-Za-z0-9]+$/);
  const products = {
    pro: required("THESISTRACE_CREEM_PRO_PRODUCT_ID", product),
    max: required("THESISTRACE_CREEM_MAX_PRODUCT_ID", product),
  };
  if (products.pro === products.max)
    throw new Error("Billing plans require distinct products");
  const expectedOrigin =
    mode === "test" ? "https://test-api.creem.io" : "https://api.creem.io";
  const apiOrigin = environment.THESISTRACE_CREEM_API_ORIGIN || expectedOrigin;
  const parsed = new URL(apiOrigin);
  const isolated =
    runtime === "test" &&
    mode === "test" &&
    parsed.protocol === "http:" &&
    ["127.0.0.1", "localhost", "creem-fake", "resend-fake"].includes(
      parsed.hostname,
    );
  if (
    apiOrigin !== parsed.origin ||
    (apiOrigin !== expectedOrigin && !isolated)
  )
    throw new Error("Invalid Creem API origin");
  return { mode, apiOrigin, apiKey, webhookSecret, products };
}
