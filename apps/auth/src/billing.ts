import { AuthOperationCoordinator } from "./coordination.js";
import { CreemError } from "creem/models/errors/creemerror.js";
import { Creem } from "creem";
import type { Pool, PoolClient } from "pg";
import type { BillingSettings } from "./billing-config.js";
import {
  BillingError,
  type BillingCommandInput,
  type BillingCommandKind,
  type BillingCommandResult,
  type BillingOperations,
  type BillingPrincipal,
  type BillingSummary,
  type PaidPlan,
} from "./billing-contract.js";
import { effectivePlan } from "./billing-entitlements.js";
import { BillingEvents } from "./billing-events.js";
import { BillingProvider, entityId, paymentUrl } from "./billing-provider.js";
import {
  recordBillingReview,
  paidEntitlements,
  researcherPlan,
} from "./billing-store.js";
import { planConfiguration } from "./quota-policy.js";

type Account = {
  researcher_id: string;
  customer_id: string | null;
  subscription_id: string | null;
  checkout_request_id: string;
  checkout_plan: PaidPlan | null;
  checkout_id: string | null;
  checkout_url: string | null;
  provider_status: string | null;
  renewal_plan: PaidPlan | null;
};
type Command = {
  id: string;
  researcher_id: string;
  kind: BillingCommandKind;
  plan_key: PaidPlan | null;
  status: "prepared" | "dispatched" | "completed" | "uncertain";
  result: BillingCommandResult | null;
};

export class BillingService implements BillingOperations {
  private readonly provider: BillingProvider;
  private readonly events: BillingEvents;
  private readonly clock: () => Date;
  private readonly pool: Pool;
  private readonly coordination: AuthOperationCoordinator;
  constructor(
    private readonly options: Readonly<{
      pool: Pool;
      settings: BillingSettings;
      publicOrigin: string;
      client?: Creem;
      clock?: () => Date;
    }>,
  ) {
    this.pool = options.pool;
    this.coordination = new AuthOperationCoordinator(this.pool);
    this.clock = options.clock ?? (() => new Date());
    this.provider = new BillingProvider(options.settings, options.client);
    this.events = new BillingEvents(this.pool, this.provider, this.clock);
  }
  async summary(id: string): Promise<BillingSummary> {
    const now = this.clock(),
      payments = await paidEntitlements(this.pool, id, now),
      plan = effectivePlan(payments, now);
    const account = (
      await this.pool.query<Account>(
        "SELECT * FROM auth.billing_account WHERE researcher_id=$1",
        [id],
      )
    ).rows[0];
    const open =
      (
        await this.pool.query(
          "SELECT 1 FROM auth.billing_command WHERE researcher_id=$1 AND (status<>'completed' OR (kind='change' AND result->>'status'='processing')) LIMIT 1",
          [id],
        )
      ).rowCount !== 0;
    const ends = payments
      .filter((p) => effectivePlan([p], now) === plan)
      .map((p) => p.endsAt.getTime());
    return {
      plan,
      paid_until:
        plan === "free" || ends.length === 0
          ? null
          : new Date(Math.max(...ends)).toISOString(),
      renewal_plan: account?.renewal_plan ?? null,
      subscription_status: account?.provider_status ?? null,
      checkout_available: this.provider.enabled,
      pending_checkout_url: account?.subscription_id
        ? null
        : (account?.checkout_url ?? null),
      pending_operation: open,
      plans: planConfiguration.plans,
    };
  }
  async command(
    principal: BillingPrincipal,
    kind: BillingCommandKind,
    input: BillingCommandInput,
  ): Promise<BillingCommandResult> {
    this.provider.configuration;
    const client = await this.pool.connect(),
      lock = `billing:${principal.id}`;
    let locked = false,
      destroyed = false;
    try {
      await client.query("SELECT pg_advisory_lock(hashtextextended($1,0))", [
        lock,
      ]);
      locked = true;
      const previous = (
        await client.query<Command>(
          "SELECT * FROM auth.billing_command WHERE id=$1",
          [input.request_id],
        )
      ).rows[0];
      if (previous) {
        if (
          previous.researcher_id !== principal.id ||
          previous.kind !== kind ||
          previous.plan_key !== (input.plan ?? null)
        )
          throw new BillingError("BILLING_REQUEST_CONFLICT");
        return previous.status === "completed"
          ? previous.result!
          : { status: "processing" };
      }
      if (
        (
          await client.query(
            "SELECT 1 FROM auth.billing_command WHERE researcher_id=$1 AND status<>'completed' LIMIT 1",
            [principal.id],
          )
        ).rowCount
      )
        throw new BillingError("BILLING_OPERATION_PENDING");
      await client.query(
        "INSERT INTO auth.billing_account(researcher_id) VALUES($1) ON CONFLICT DO NOTHING",
        [principal.id],
      );
      const account = (
        await client.query<Account>(
          "SELECT * FROM auth.billing_account WHERE researcher_id=$1",
          [principal.id],
        )
      ).rows[0]!;
      if (kind !== "cancel") {
        if (!input.plan) throw new BillingError("BILLING_REQUEST_INVALID", 400);
        await this.provider.product(input.plan);
      }
      if (kind === "checkout") {
        if (account.subscription_id && account.provider_status !== "canceled")
          throw new BillingError("BILLING_SUBSCRIPTION_EXISTS");
        if (account.checkout_url) {
          const checkout = await this.provider.sdk.checkouts.retrieve(
            account.checkout_id!,
          );
          this.provider.checkMode(checkout.mode);
          if (checkout.status !== "expired")
            throw new BillingError("BILLING_CHECKOUT_PENDING");
        }
      } else if (!account.subscription_id)
        throw new BillingError("BILLING_SUBSCRIPTION_REQUIRED");
      // Read-only preflight precedes the dispatch fence, so a failed GET can be retried.
      let subscription =
        kind === "checkout"
          ? null
          : await this.provider.sdk.subscriptions.get(account.subscription_id!);
      if (subscription) {
        this.provider.checkMode(subscription.mode);
        if (entityId(subscription.customer) !== account.customer_id)
          throw new BillingError("BILLING_OWNER_MISMATCH", 503);
      }
      const paid =
        kind === "change"
          ? await researcherPlan(client, principal.id, this.clock())
          : "free";
      const higher =
        kind === "change" &&
        planConfiguration.plans[input.plan!].monthly_price_usd >
          planConfiguration.plans[paid].monthly_price_usd;
      if (kind === "change") {
        if (
          (
            await client.query(
              "SELECT 1 FROM auth.billing_command WHERE researcher_id=$1 AND kind='change' AND result->>'status'='processing' LIMIT 1",
              [principal.id],
            )
          ).rowCount
        )
          throw new BillingError("BILLING_OPERATION_PENDING");
        // The existing product can remain after a refund or dispute. Reapplying
        // it makes no charge and cannot restore a payment-backed grant.
        if (
          higher &&
          entityId(subscription!.product) ===
            this.provider.productId(input.plan!)
        )
          throw new BillingError("BILLING_PAYMENT_REQUIRED");
      }
      // Commit the dispatch fence before contacting the payment provider. An
      // ambiguous response is reconciled; it never causes a blind second charge.
      await client.query("BEGIN");
      try {
        await client.query(
          "INSERT INTO auth.billing_command(id,researcher_id,kind,plan_key,status) VALUES($1,$2,$3,$4,'dispatched')",
          [input.request_id, principal.id, kind, input.plan ?? null],
        );
        if (kind === "checkout")
          await client.query(
            "UPDATE auth.billing_account SET checkout_request_id=$2,checkout_plan=$3,checkout_id=NULL,checkout_url=NULL,subscription_id=NULL,provider_status=NULL,renewal_plan=NULL WHERE researcher_id=$1",
            [principal.id, input.request_id, input.plan],
          );
        await client.query("COMMIT");
      } catch (error) {
        await client.query("ROLLBACK");
        throw error;
      }
      try {
        let result: BillingCommandResult;
        if (kind === "checkout") {
          const checkout = await this.provider.sdk.checkouts.create({
            requestId: input.request_id,
            productId: this.provider.productId(input.plan!),
            units: 1,
            customer: account.customer_id
              ? { id: account.customer_id }
              : { email: principal.email },
            metadata: { billing_request_id: input.request_id },
            successUrl: `${this.options.publicOrigin}/billing?payment_return=1`,
          });
          this.provider.checkMode(checkout.mode);
          const url = paymentUrl(checkout.checkoutUrl);
          await client.query(
            "UPDATE auth.billing_account SET checkout_id=$2,checkout_url=$3,updated_at=now() WHERE researcher_id=$1 AND checkout_request_id=$4",
            [principal.id, checkout.id, url, input.request_id],
          );
          result = { status: "completed", url };
        } else {
          if (!subscription)
            throw new BillingError("BILLING_SUBSCRIPTION_REQUIRED");
          if (kind === "cancel") {
            if (!["scheduled_cancel", "canceled"].includes(subscription.status))
              subscription = await this.provider.sdk.subscriptions.cancel(
                subscription.id,
                { mode: "scheduled" },
              );
            result = { status: "completed" };
          } else {
            if (
              entityId(subscription.product) !==
              this.provider.productId(input.plan!)
            )
              subscription = await this.provider.sdk.subscriptions.upgrade(
                subscription.id,
                {
                  productId: this.provider.productId(input.plan!),
                  updateBehavior: higher
                    ? "proration-charge-immediately"
                    : "proration-none",
                },
              );
            result = { status: higher ? "processing" : "completed" };
          }
          await client.query(
            "UPDATE auth.billing_account SET provider_status=$2,renewal_plan=$3,updated_at=now() WHERE researcher_id=$1",
            [
              principal.id,
              subscription.status,
              this.provider.planForProduct(entityId(subscription.product)),
            ],
          );
        }
        await client.query(
          "UPDATE auth.billing_command SET status='completed',result=$2,updated_at=now() WHERE id=$1",
          [input.request_id, JSON.stringify(result)],
        );
        return result;
      } catch (error) {
        if (
          error instanceof CreemError &&
          [400, 401, 403, 404, 422].includes(error.statusCode)
        ) {
          const result: BillingCommandResult = {
            status: "failed",
            code: "BILLING_PROVIDER_REJECTED",
          };
          await client.query(
            "UPDATE auth.billing_command SET status='completed',result=$2,updated_at=now() WHERE id=$1",
            [input.request_id, JSON.stringify(result)],
          );
          return result;
        }
        process.stderr.write(
          JSON.stringify({
            event: "billing_command_uncertain",
            command_id: input.request_id,
            code:
              error instanceof BillingError
                ? error.code
                : error instanceof Error
                  ? error.name
                  : "UNKNOWN_FAILURE",
          }) + "\n",
        );
        await client
          .query(
            "UPDATE auth.billing_command SET status='uncertain',updated_at=now() WHERE id=$1",
            [input.request_id],
          )
          .catch(() => undefined);
        return { status: "processing" };
      }
    } finally {
      if (locked) {
        try {
          await client.query(
            "SELECT pg_advisory_unlock(hashtextextended($1,0))",
            [lock],
          );
        } catch {
          client.release(true);
          destroyed = true;
        }
      }
      if (!destroyed) client.release();
    }
  }
  async portal(id: string): Promise<string> {
    const account = (
      await this.pool.query<Account>(
        "SELECT * FROM auth.billing_account WHERE researcher_id=$1",
        [id],
      )
    ).rows[0];
    if (!account?.customer_id)
      throw new BillingError("BILLING_SUBSCRIPTION_REQUIRED");
    return paymentUrl(
      (
        await this.provider.sdk.customers.generateBillingLinks({
          customerId: account.customer_id,
        })
      ).customerPortalLink,
    );
  }
  /** Manual negative acknowledgement after the merchant has confirmed no provider effect. */
  async rejectUnappliedCommand(id: string, evidence: string) {
    if (!/^[A-Za-z0-9_.:/-]{3,200}$/.test(evidence))
      throw new BillingError("BILLING_REVIEW_EVIDENCE_REQUIRED", 400);
    const command = (
      await this.pool.query<Command>(
        "SELECT * FROM auth.billing_command WHERE id=$1",
        [id],
      )
    ).rows[0];
    if (!command) throw new BillingError("BILLING_REQUEST_INVALID", 400);
    await this.coordination.run(
      [`billing:${command.researcher_id}`],
      async (client) => {
        const current = (
          await client.query<Command>(
            "SELECT * FROM auth.billing_command WHERE id=$1",
            [id],
          )
        ).rows[0]!;
        if (current.status === "completed")
          throw new BillingError("BILLING_OPERATION_ALREADY_APPLIED");
        const account = (
          await client.query<Account>(
            "SELECT * FROM auth.billing_account WHERE researcher_id=$1",
            [command.researcher_id],
          )
        ).rows[0]!;
        if (command.kind === "checkout") {
          if (account.checkout_request_id !== id || account.subscription_id)
            throw new BillingError("BILLING_OPERATION_ALREADY_APPLIED");
          if (account.checkout_id) {
            const checkout = await this.provider.sdk.checkouts.retrieve(
              account.checkout_id,
            );
            this.provider.checkMode(checkout.mode);
            if (checkout.requestId !== id || checkout.status !== "expired")
              throw new BillingError("BILLING_OPERATION_ALREADY_APPLIED");
          }
          // Without a returned Checkout ID only the merchant can establish that
          // no request is pending or completed. The required evidence is audited.
        } else {
          const subscription = await this.provider.sdk.subscriptions.get(
            account.subscription_id!,
          );
          this.provider.checkMode(subscription.mode);
          if (
            subscription.id !== account.subscription_id ||
            entityId(subscription.customer) !== account.customer_id
          )
            throw new BillingError("BILLING_OWNER_MISMATCH");
          if (
            (command.kind === "cancel" &&
              ["scheduled_cancel", "canceled"].includes(subscription.status)) ||
            (command.kind === "change" &&
              entityId(subscription.product) ===
                this.provider.productId(command.plan_key!))
          )
            throw new BillingError("BILLING_OPERATION_ALREADY_APPLIED");
        }
        await client.query("BEGIN");
        try {
          const result = {
            status: "failed",
            code: "BILLING_OPERATION_NOT_APPLIED",
          };
          await client.query(
            "UPDATE auth.billing_command SET status='completed',result=$2,updated_at=now() WHERE id=$1",
            [id, JSON.stringify(result)],
          );
          await recordBillingReview(
            client,
            `review:${id}:${this.clock().getTime()}`,
            "merchant.command_not_applied",
            { command_id: id, evidence },
          );
          await client.query("COMMIT");
        } catch (error) {
          await client.query("ROLLBACK");
          throw error;
        }
      },
    );
  }
  async recoverCheckout(requestId: string, checkoutId: string) {
    const checkout = await this.provider.sdk.checkouts.retrieve(checkoutId);
    this.provider.checkMode(checkout.mode);
    if (checkout.requestId !== requestId || checkout.status === "expired")
      throw new BillingError("BILLING_CHECKOUT_INVALID");
    const command = (
      await this.pool.query<Command>(
        "SELECT * FROM auth.billing_command WHERE id=$1 AND kind='checkout'",
        [requestId],
      )
    ).rows[0];
    if (
      !command ||
      entityId(checkout.product) !== this.provider.productId(command.plan_key!)
    )
      throw new BillingError("BILLING_OWNER_MISMATCH");
    const url = paymentUrl(checkout.checkoutUrl);
    const updated = await this.pool.query(
      "UPDATE auth.billing_account SET checkout_id=$2,checkout_url=$3 WHERE researcher_id=$1 AND checkout_request_id=$4 AND subscription_id IS NULL",
      [command.researcher_id, checkout.id, url, requestId],
    );
    if (updated.rowCount !== 1)
      throw new BillingError("BILLING_OWNER_MISMATCH");
    await this.pool.query(
      "UPDATE auth.billing_command SET status='completed',result=$2,updated_at=now() WHERE id=$1",
      [requestId, JSON.stringify({ status: "completed", url })],
    );
  }
  resolveDispute(transactionId: string, evidence: string) {
    return this.events.resolveDispute(transactionId, evidence);
  }
  replayEvent(id: string) {
    return this.events.process(id);
  }
  receiveWebhook(raw: string, headers: Headers) {
    return this.events.receive(raw, headers);
  }
  async reconcile() {
    if (!this.provider.enabled) return;
    await this.events.reconcile();
    const commands = (
      await this.pool.query<Command>(
        "SELECT * FROM auth.billing_command WHERE status<>'completed' OR (kind='change' AND result->>'status'='processing') ORDER BY updated_at,id LIMIT 10",
      )
    ).rows;
    for (const command of commands) {
      await this.coordination
        .run([`billing:${command.researcher_id}`], async (client) => {
          const current = (
            await client.query<Command>(
              "SELECT * FROM auth.billing_command WHERE id=$1",
              [command.id],
            )
          ).rows[0];
          const account = (
            await client.query<Account>(
              "SELECT * FROM auth.billing_account WHERE researcher_id=$1",
              [command.researcher_id],
            )
          ).rows[0];
          let result: BillingCommandResult | undefined;
          let renewalState: { status: string; plan: PaidPlan } | undefined;
          if (
            current &&
            (current.status !== "completed" ||
              current.result?.status === "processing") &&
            account
          ) {
            if (
              command.kind === "checkout" &&
              account.checkout_id &&
              account.checkout_request_id === command.id
            ) {
              const checkout = await this.provider.sdk.checkouts.retrieve(
                account.checkout_id,
              );
              this.provider.checkMode(checkout.mode);
              if (checkout.requestId !== command.id)
                throw new BillingError("BILLING_OWNER_MISMATCH", 503);
              if (checkout.checkoutUrl)
                result = {
                  status: "completed",
                  url: paymentUrl(checkout.checkoutUrl),
                };
            } else if (command.kind !== "checkout" && account.subscription_id) {
              const subscription = await this.provider.sdk.subscriptions.get(
                account.subscription_id,
              );
              this.provider.checkMode(subscription.mode);
              if (entityId(subscription.customer) !== account.customer_id)
                throw new BillingError("BILLING_OWNER_MISMATCH", 503);
              const renewal = this.provider.planForProduct(
                entityId(subscription.product),
              );
              renewalState = { status: subscription.status, plan: renewal };
              if (
                command.kind === "cancel" &&
                ["scheduled_cancel", "canceled"].includes(subscription.status)
              )
                result = { status: "completed" };
              if (command.kind === "change") {
                const paid = await researcherPlan(
                  client,
                  command.researcher_id,
                  this.clock(),
                );
                if (
                  renewal === command.plan_key &&
                  planConfiguration.plans[paid].monthly_price_usd >=
                    planConfiguration.plans[command.plan_key!].monthly_price_usd
                )
                  result = { status: "completed" };
                else if (subscription.status === "canceled")
                  // This subscription can no longer complete the requested
                  // upgrade. A later verified payment still projects normally.
                  result = {
                    status: "failed",
                    code: "BILLING_PAYMENT_NOT_COMPLETED",
                  };
                else if (renewal === command.plan_key)
                  result = { status: "processing" };
              }
            }
          }
          await client.query("BEGIN");
          try {
            if (renewalState)
              await client.query(
                "UPDATE auth.billing_account SET provider_status=$2,renewal_plan=$3,updated_at=now() WHERE researcher_id=$1",
                [command.researcher_id, renewalState.status, renewalState.plan],
              );
            if (result)
              await client.query(
                "UPDATE auth.billing_command SET status='completed',result=$2,updated_at=now() WHERE id=$1",
                [command.id, JSON.stringify(result)],
              );
            // Include commands without a recoverable provider ID in fair reconciliation.
            await client.query(
              "UPDATE auth.billing_command SET updated_at=now() WHERE id=$1",
              [command.id],
            );
            await client.query("COMMIT");
          } catch (error) {
            await client.query("ROLLBACK");
            throw error;
          }
        })
        .catch(async () => {
          await this.pool
            .query(
              "UPDATE auth.billing_command SET updated_at=now() WHERE id=$1",
              [command.id],
            )
            .catch(() => undefined);
        });
    }
  }
}
