import { Hono } from "hono";
import { z } from "zod";
import { WebhookVerificationError } from "creem/webhooks";
import {
  BillingError,
  type BillingOperations,
  type BillingPrincipal,
} from "./billing-contract.js";
import { isJsonContentType } from "./http-media-type.js";

const purchase = z
  .object({ request_id: z.uuid(), plan: z.enum(["pro", "max"]) })
  .strict();
const cancellation = z.object({ request_id: z.uuid() }).strict();
export function createBillingApp(
  dependencies: Readonly<{
    billing: BillingOperations;
    publicOrigin: string;
    requireResearcher: (
      request: Request,
    ) => Promise<BillingPrincipal | Response>;
  }>,
) {
  const app = new Hono();
  app.use("*", async (c, next) => {
    c.header("Cache-Control", "no-store");
    await next();
  });
  app.onError((error, c) => {
    if (error instanceof BillingError)
      return c.json({ code: error.code }, error.status);
    if (error instanceof WebhookVerificationError)
      return c.json({ code: "BILLING_WEBHOOK_INVALID" }, 400);
    return c.json({ code: "BILLING_UNAVAILABLE" }, 503);
  });
  app.post("/webhook", async (c) => {
    await dependencies.billing.receiveWebhook(
      await c.req.text(),
      c.req.raw.headers,
    );
    return c.body(null, 204);
  });
  app.use("*", async (c, next) => {
    if (
      c.req.method !== "GET" &&
      c.req.header("origin") !== dependencies.publicOrigin
    ) {
      return c.json({ code: "ORIGIN_NOT_ALLOWED" }, 403);
    }
    await next();
  });
  app.get("/", async (c) => {
    const principal = await dependencies.requireResearcher(c.req.raw);
    if (principal instanceof Response) return principal;
    return c.json(await dependencies.billing.summary(principal.id));
  });
  for (const kind of ["checkout", "change", "cancel"] as const) {
    app.post(`/${kind}`, async (c) => {
      const principal = await dependencies.requireResearcher(c.req.raw);
      if (principal instanceof Response) return principal;
      if (!isJsonContentType(c.req.header("content-type") ?? null))
        return c.json({ code: "BILLING_REQUEST_INVALID" }, 400);
      const body = await c.req.json().catch(() => null);
      const parsed = (kind === "cancel" ? cancellation : purchase).safeParse(
        body,
      );
      if (!parsed.success)
        return c.json({ code: "BILLING_REQUEST_INVALID" }, 400);
      return c.json(
        await dependencies.billing.command(principal, kind, parsed.data),
      );
    });
  }
  app.post("/portal", async (c) => {
    const principal = await dependencies.requireResearcher(c.req.raw);
    if (principal instanceof Response) return principal;
    return c.json({ url: await dependencies.billing.portal(principal.id) });
  });
  return app;
}
