import { AuthOperationCoordinator } from "./coordination.js";
import type { SubscriptionEntity } from "creem/models/components/subscriptionentity.js";
import { recordBillingReview } from "./billing-store.js";
import { createHash } from "node:crypto";
import type { Pool, PoolClient } from "pg";
import {
  constructWebhookEventEntity,
  parseWebhookEventEntity,
  WebhookVerificationError,
} from "creem/webhooks";
import type { TransactionEntity } from "creem/models/components/transactionentity.js";
import { BillingError } from "./billing-contract.js";
import { BillingProvider, entityId } from "./billing-provider.js";

type Event = ReturnType<typeof parseWebhookEventEntity>;
const objectId = (id: string) => id.length > 0 && id.length <= 256;

/** Verified inbox, transactional projections and read-only reconciliation. */
export class BillingEvents {
  private transactionCursor = "";
  private readonly coordination: AuthOperationCoordinator;
  constructor(
    private readonly pool: Pool,
    private readonly provider: BillingProvider,
    private readonly clock: () => Date,
  ) {
    this.coordination = new AuthOperationCoordinator(pool);
  }
  async receive(raw: string, headers: Headers) {
    const settings = this.provider.configuration;
    let event: Event;
    try {
      event = await constructWebhookEventEntity(raw, headers, {
        secret: settings.webhookSecret,
      });
    } catch (error) {
      if (error instanceof WebhookVerificationError) throw error;
      throw new BillingError("BILLING_WEBHOOK_INVALID", 400);
    }
    if (!objectId(event.id))
      throw new BillingError("BILLING_WEBHOOK_INVALID", 400);
    if ("mode" in event.object)
      this.provider.checkMode(event.object.mode as string);
    const digest = createHash("sha256").update(raw).digest();
    await this.pool.query(
      "INSERT INTO auth.billing_event(id,event_type,raw_body,body_sha256) VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING",
      [event.id, event.eventType, raw, digest],
    );
    const saved = (
      await this.pool.query<{ body_sha256: Buffer }>(
        "SELECT body_sha256 FROM auth.billing_event WHERE id=$1",
        [event.id],
      )
    ).rows[0];
    if (!saved?.body_sha256.equals(digest))
      throw new BillingError("BILLING_EVENT_CONFLICT", 400);
    await this.process(event.id);
  }
  private async lock(client: PoolClient, id: string) {
    await client.query("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", [
      `billing:${id}`,
    ]);
  }
  private async findOwner(
    client: Pool | PoolClient,
    subscriptionId: string,
    transactionId?: string,
  ) {
    const rows = (
      await client.query<{ researcher_id: string }>(
        `SELECT researcher_id FROM auth.billing_account WHERE subscription_id=$1
       UNION SELECT researcher_id FROM auth.billing_payment WHERE subscription_id=$1 OR transaction_id=$2`,
        [subscriptionId, transactionId ?? null],
      )
    ).rows;
    if (rows.length !== 1) throw new BillingError("BILLING_OWNER_PENDING", 503);
    return rows[0]!.researcher_id;
  }
  private async owner(
    client: PoolClient,
    subscriptionId: string,
    transactionId?: string,
  ) {
    const id = await this.findOwner(client, subscriptionId, transactionId);
    await this.lock(client, id);
    return id;
  }
  private async eventOwner(event: Event): Promise<string | undefined> {
    if (event.eventType === "checkout.completed") {
      if (!event.object.requestId || event.object.status !== "completed")
        throw new BillingError("BILLING_CHECKOUT_INVALID", 503);
      const command = (
        await this.pool.query<{ researcher_id: string }>(
          "SELECT researcher_id FROM auth.billing_command WHERE id::text=$1 AND kind='checkout'",
          [event.object.requestId],
        )
      ).rows[0];
      if (!command) throw new BillingError("BILLING_OWNER_PENDING", 503);
      return command.researcher_id;
    }
    if (
      event.eventType === "refund.created" ||
      event.eventType === "dispute.created"
    ) {
      const transaction = await this.provider.sdk.transactions.getById(
        event.object.transaction.id,
      );
      if (
        transaction.id !== event.object.transaction.id ||
        !transaction.subscription
      )
        throw new BillingError("BILLING_TRANSACTION_INVALID", 503);
      return this.findOwner(
        this.pool,
        transaction.subscription,
        transaction.id,
      );
    }
    if (event.eventType.startsWith("subscription."))
      return this.findOwner(this.pool, event.object.id);
    return undefined;
  }
  private async evidence(
    event: Event,
  ): Promise<{
    subscription?: SubscriptionEntity;
    transaction?: TransactionEntity;
  }> {
    if (event.eventType === "checkout.completed")
      return {
        subscription: await this.provider.sdk.subscriptions.get(
          entityId(event.object.subscription),
        ),
      };
    if (event.eventType === "subscription.paid") {
      const id =
        event.object.lastTransactionId ?? event.object.lastTransaction?.id;
      if (!id) throw new BillingError("BILLING_PAYMENT_EVIDENCE_MISSING", 503);
      return {
        transaction: await this.provider.sdk.transactions.getById(id),
        subscription: await this.provider.sdk.subscriptions.get(
          event.object.id,
        ),
      };
    }
    if (
      event.eventType === "refund.created" ||
      event.eventType === "dispute.created"
    )
      return {
        transaction: await this.provider.sdk.transactions.getById(
          event.object.transaction.id,
        ),
      };
    if (event.eventType.startsWith("subscription."))
      return {
        subscription: await this.provider.sdk.subscriptions.get(
          event.object.id,
        ),
      };
    return {};
  }
  private checkTransaction(
    transaction: TransactionEntity,
    subscriptionId: string,
    customerId?: string,
  ) {
    this.provider.checkMode(transaction.mode);
    if (
      transaction.currency !== "USD" ||
      transaction.subscription !== subscriptionId ||
      (customerId !== undefined &&
        transaction.customer !== undefined &&
        transaction.customer !== null &&
        transaction.customer !== customerId)
    )
      throw new BillingError("BILLING_TRANSACTION_INVALID", 503);
    const amount = transaction.amountPaid ?? transaction.amount;
    const refunded =
      transaction.status === "refunded"
        ? amount
        : (transaction.refundedAmount ?? 0);
    if (
      !Number.isSafeInteger(amount) ||
      amount <= 0 ||
      !Number.isSafeInteger(refunded) ||
      refunded < 0 ||
      refunded > amount ||
      (transaction.status !== "refunded" && refunded === amount)
    )
      throw new BillingError("BILLING_TRANSACTION_INVALID", 503);
    return { amount, refunded, disputed: transaction.status === "chargedBack" };
  }
  private async synchronizeAccount(
    client: PoolClient,
    subscriptionId: string,
    subscription: SubscriptionEntity,
  ) {
    this.provider.checkMode(subscription.mode);
    if (subscription.id !== subscriptionId)
      throw new BillingError("BILLING_OWNER_MISMATCH", 503);
    const result = await client.query(
      "UPDATE auth.billing_account SET provider_status=$2,renewal_plan=$3,updated_at=now() WHERE subscription_id=$1 AND customer_id=$4 RETURNING researcher_id",
      [
        subscriptionId,
        subscription.status,
        this.provider.planForProduct(entityId(subscription.product)),
        entityId(subscription.customer),
      ],
    );
    // A historical subscription can have payment adjustments after a new
    // subscription is created. It must not overwrite that new account state.
    return result.rows[0]?.researcher_id as string | undefined;
  }
  private async projectTransaction(
    client: PoolClient,
    transaction: TransactionEntity,
  ) {
    const subscriptionId = transaction.subscription;
    if (!subscriptionId)
      throw new BillingError("BILLING_TRANSACTION_INVALID", 503);
    const state = this.checkTransaction(transaction, subscriptionId);
    await client.query(
      `INSERT INTO auth.billing_adjustment(transaction_id,refunded_amount,disputed)
      VALUES($1,$2,$3) ON CONFLICT(transaction_id) DO UPDATE SET
      refunded_amount=GREATEST(auth.billing_adjustment.refunded_amount,EXCLUDED.refunded_amount),
      disputed=auth.billing_adjustment.disputed OR EXCLUDED.disputed,updated_at=now()`,
      [transaction.id, state.refunded, state.disputed],
    );
    await client.query(
      `UPDATE auth.billing_payment SET refunded_amount=LEAST(amount,GREATEST(refunded_amount,$2)),
      disputed=disputed OR $3 WHERE transaction_id=$1`,
      [transaction.id, state.refunded, state.disputed],
    );
  }
  /** Owner-only maintenance entrypoint; the merchant must review Creem dispute resolution first. */
  async resolveDispute(transactionId: string, evidence: string) {
    if (!/^[A-Za-z0-9_.:/-]{3,200}$/.test(evidence))
      throw new BillingError("BILLING_REVIEW_EVIDENCE_REQUIRED", 400);
    const initial = await this.provider.sdk.transactions.getById(transactionId);
    if (initial.id !== transactionId || !initial.subscription)
      throw new BillingError("BILLING_TRANSACTION_INVALID", 503);
    const researcher = await this.findOwner(
      this.pool,
      initial.subscription,
      transactionId,
    );
    await this.coordination.run([`billing:${researcher}`], async (client) => {
      const transaction =
        await this.provider.sdk.transactions.getById(transactionId);
      if (transaction.id !== transactionId)
        throw new BillingError("BILLING_TRANSACTION_INVALID", 503);
      await client.query("BEGIN");
      try {
        if (
          !transaction.subscription ||
          !["paid", "partialRefund"].includes(transaction.status)
        )
          throw new BillingError("BILLING_PAYMENT_UNCONFIRMED", 409);
        const owner = await this.owner(
          client,
          transaction.subscription,
          transactionId,
        );
        const payment = (
          await client.query<{ amount: number }>(
            "SELECT amount FROM auth.billing_payment WHERE transaction_id=$1 AND researcher_id=$2 FOR UPDATE",
            [transactionId, owner],
          )
        ).rows[0];
        const state = this.checkTransaction(
          transaction,
          transaction.subscription,
        );
        if (
          !payment ||
          payment.amount !== state.amount ||
          state.refunded >= state.amount
        )
          throw new BillingError("BILLING_PAYMENT_UNCONFIRMED", 409);
        await client.query(
          "UPDATE auth.billing_adjustment SET disputed=false,dispute_resolved_at=$2,updated_at=now() WHERE transaction_id=$1",
          [transactionId, this.clock()],
        );
        await client.query(
          "UPDATE auth.billing_payment SET disputed=false,refunded_amount=GREATEST(refunded_amount,$2) WHERE transaction_id=$1",
          [transactionId, state.refunded],
        );
        await recordBillingReview(
          client,
          `review:${transactionId}:${this.clock().getTime()}`,
          "merchant.dispute_resolved",
          { transaction_id: transactionId, evidence },
        );
        await client.query("COMMIT");
      } catch (error) {
        await client.query("ROLLBACK");
        throw error;
      }
    });
  }
  async process(id: string) {
    try {
      const saved = (
        await this.pool.query<{ raw_body: string; processed_at: Date | null }>(
          "SELECT raw_body,processed_at FROM auth.billing_event WHERE id=$1",
          [id],
        )
      ).rows[0];
      if (!saved || saved.processed_at) return;
      const event = parseWebhookEventEntity(saved.raw_body);
      const owner = await this.eventOwner(event);
      await this.coordination.run(
        [owner ? `billing:${owner}` : `billing-event:${id}`],
        async (client) => {
          const current = (
            await client.query<{ processed_at: Date | null }>(
              "SELECT processed_at FROM auth.billing_event WHERE id=$1",
              [id],
            )
          ).rows[0];
          if (!current || current.processed_at) return;
          const evidence = await this.evidence(event);
          await this.projectEvent(client, id, event, evidence);
        },
      );
    } catch (error) {
      process.stderr.write(
        JSON.stringify({
          event: "billing_event_processing_failed",
          event_id: id,
          code:
            error instanceof BillingError
              ? error.code
              : error instanceof Error
                ? error.name
                : "UNKNOWN_FAILURE",
        }) + "\n",
      );
      await this.pool
        .query(
          "UPDATE auth.billing_event SET attempts=attempts+1,failure_code='BILLING_EVENT_PROCESSING_FAILED' WHERE id=$1 AND processed_at IS NULL",
          [id],
        )
        .catch(() => undefined);
      throw error;
    }
  }
  private async projectEvent(
    client: PoolClient,
    id: string,
    event: Event,
    evidence: {
      subscription?: SubscriptionEntity;
      transaction?: TransactionEntity;
    },
  ) {
    await client.query("BEGIN");
    try {
      await client.query("SET LOCAL lock_timeout='5s'");
      const saved = (
        await client.query<{ processed_at: Date | null }>(
          "SELECT processed_at FROM auth.billing_event WHERE id=$1 FOR UPDATE",
          [id],
        )
      ).rows[0];
      if (!saved || saved.processed_at) {
        await client.query("COMMIT");
        return;
      }
      if (event.eventType === "checkout.completed") {
        const checkout = event.object;
        this.provider.checkMode(checkout.mode);
        const requestId = checkout.requestId;
        if (!requestId || checkout.status !== "completed")
          throw new BillingError("BILLING_CHECKOUT_INVALID", 503);
        const command = (
          await client.query<{ researcher_id: string; plan_key: string }>(
            "SELECT researcher_id,plan_key FROM auth.billing_command WHERE id::text=$1 AND kind='checkout'",
            [requestId],
          )
        ).rows[0];
        if (!command) throw new BillingError("BILLING_OWNER_PENDING", 503);
        await this.lock(client, command.researcher_id);
        if (
          entityId(checkout.product) !==
          this.provider.productId(command.plan_key as "pro" | "max")
        )
          throw new BillingError("BILLING_CHECKOUT_INVALID", 503);
        const subscriptionId = entityId(checkout.subscription),
          customerId = entityId(checkout.customer);
        const subscription = evidence.subscription!;
        this.provider.checkMode(subscription.mode);
        if (entityId(subscription.customer) !== customerId)
          throw new BillingError("BILLING_OWNER_MISMATCH", 503);
        const updated = await client.query(
          `UPDATE auth.billing_account SET customer_id=$2,subscription_id=$3,
          provider_status=$4,renewal_plan=$5,checkout_id=$6,checkout_url=NULL,updated_at=now()
          WHERE researcher_id=$1 AND checkout_request_id::text=$7
            AND (subscription_id IS NULL OR subscription_id=$3 OR provider_status='canceled') RETURNING researcher_id`,
          [
            command.researcher_id,
            customerId,
            subscriptionId,
            subscription.status,
            this.provider.planForProduct(entityId(subscription.product)),
            checkout.id,
            requestId,
          ],
        );
        if (updated.rowCount !== 1)
          throw new BillingError("BILLING_OWNER_MISMATCH", 503);
        await client.query(
          "UPDATE auth.billing_command SET status='completed',result=$2,updated_at=now() WHERE id::text=$1",
          [requestId, JSON.stringify({ status: "completed" })],
        );
      } else if (event.eventType === "subscription.paid") {
        const subscription = event.object;
        this.provider.checkMode(subscription.mode);
        const owner = await this.owner(client, subscription.id);
        const account = (
          await client.query<{ customer_id: string | null }>(
            "SELECT customer_id FROM auth.billing_account WHERE researcher_id=$1",
            [owner],
          )
        ).rows[0];
        if (account?.customer_id !== subscription.customer.id)
          throw new BillingError("BILLING_OWNER_MISMATCH", 503);
        const plan = this.provider.validateProduct(subscription.product);
        const transactionId =
          subscription.lastTransactionId ?? subscription.lastTransaction?.id;
        if (
          !transactionId ||
          (subscription.lastTransaction &&
            subscription.lastTransaction.id !== transactionId)
        )
          throw new BillingError("BILLING_PAYMENT_EVIDENCE_MISSING", 503);
        const transaction = evidence.transaction!;
        if (transaction.id !== transactionId)
          throw new BillingError("BILLING_TRANSACTION_INVALID", 503);
        const state = this.checkTransaction(
          transaction,
          subscription.id,
          subscription.customer.id,
        );
        if (
          !["paid", "partialRefund", "refunded", "chargedBack"].includes(
            transaction.status,
          )
        )
          throw new BillingError("BILLING_PAYMENT_UNCONFIRMED", 503);
        const start = subscription.currentPeriodStartDate,
          end = subscription.currentPeriodEndDate;
        if (
          !start ||
          !end ||
          !Number.isFinite(start.getTime()) ||
          end <= start ||
          (transaction.periodStart !== undefined &&
            transaction.periodStart !== start.getTime()) ||
          (transaction.periodEnd !== undefined &&
            transaction.periodEnd !== end.getTime())
        )
          throw new BillingError("BILLING_PAYMENT_PERIOD_INVALID", 503);
        await this.projectTransaction(client, transaction);
        const adjustment = (
          await client.query<{ refunded_amount: number; disputed: boolean }>(
            "SELECT refunded_amount,disputed FROM auth.billing_adjustment WHERE transaction_id=$1",
            [transaction.id],
          )
        ).rows[0]!;
        const stored = await client.query(
          `INSERT INTO auth.billing_payment(transaction_id,researcher_id,subscription_id,plan_key,starts_at,ends_at,amount,refunded_amount,disputed)
          VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9) ON CONFLICT(transaction_id) DO UPDATE SET
          refunded_amount=GREATEST(auth.billing_payment.refunded_amount,EXCLUDED.refunded_amount),
          disputed=auth.billing_payment.disputed OR EXCLUDED.disputed
          WHERE auth.billing_payment.researcher_id=EXCLUDED.researcher_id
            AND auth.billing_payment.subscription_id=EXCLUDED.subscription_id
            AND auth.billing_payment.plan_key=EXCLUDED.plan_key
            AND auth.billing_payment.starts_at=EXCLUDED.starts_at AND auth.billing_payment.ends_at=EXCLUDED.ends_at
            AND auth.billing_payment.amount=EXCLUDED.amount RETURNING transaction_id`,
          [
            transaction.id,
            owner,
            subscription.id,
            plan,
            start,
            end,
            state.amount,
            Math.min(state.amount, adjustment.refunded_amount),
            adjustment.disputed,
          ],
        );
        if (stored.rowCount !== 1)
          throw new BillingError("BILLING_PAYMENT_CONFLICT", 503);
        if (
          start <= this.clock() &&
          end > this.clock() &&
          !adjustment.disputed &&
          adjustment.refunded_amount < state.amount
        )
          await client.query(
            `UPDATE auth.billing_command SET result='{"status":"completed"}'::jsonb,updated_at=now()
            WHERE researcher_id=$1 AND kind='change' AND plan_key=$2 AND result->>'status'='processing'`,
            [owner, plan],
          );
        await this.synchronizeAccount(
          client,
          subscription.id,
          evidence.subscription!,
        );
      } else if (
        event.eventType === "refund.created" ||
        event.eventType === "dispute.created"
      ) {
        const embedded = event.object.transaction;
        const transaction = evidence.transaction!;
        if (transaction.id !== embedded.id || !transaction.subscription)
          throw new BillingError("BILLING_TRANSACTION_INVALID", 503);
        await this.owner(client, transaction.subscription, transaction.id);
        await this.projectTransaction(client, transaction);
        if (event.eventType === "dispute.created") {
          await client.query(
            `UPDATE auth.billing_adjustment SET disputed=true,updated_at=now() WHERE transaction_id=$1
            AND (dispute_resolved_at IS NULL OR dispute_resolved_at < $2)`,
            [transaction.id, new Date(event.createdAt)],
          );
          await client.query(
            "UPDATE auth.billing_payment SET disputed=true WHERE transaction_id=$1 AND EXISTS(SELECT 1 FROM auth.billing_adjustment WHERE transaction_id=$1 AND disputed)",
            [transaction.id],
          );
        }
      } else if (event.eventType.startsWith("subscription.")) {
        const subscriptionId = event.object.id;
        await this.owner(client, subscriptionId);
        await this.synchronizeAccount(
          client,
          subscriptionId,
          evidence.subscription!,
        );
      }
      await client.query(
        "UPDATE auth.billing_event SET processed_at=now(),attempts=attempts+1,failure_code=NULL WHERE id=$1",
        [id],
      );
      await client.query("COMMIT");
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    }
  }
  async reconcile() {
    const pending = (
      await this.pool.query<{ id: string }>(
        "SELECT id FROM auth.billing_event WHERE processed_at IS NULL ORDER BY attempts,received_at LIMIT 10",
      )
    ).rows;
    for (const row of pending)
      await this.process(row.id).catch(() => undefined);
    const payments = (
      await this.pool.query<{
        transaction_id: string;
        subscription_id: string;
        researcher_id: string;
      }>(
        "SELECT transaction_id,subscription_id,researcher_id FROM auth.billing_payment WHERE ends_at>$1 AND transaction_id>$2 ORDER BY transaction_id LIMIT 10",
        [this.clock(), this.transactionCursor],
      )
    ).rows;
    if (payments.length === 0) this.transactionCursor = "";
    for (const payment of payments) {
      this.transactionCursor = payment.transaction_id;
      await this.coordination
        .run([`billing:${payment.researcher_id}`], async (client) => {
          const transaction = await this.provider.sdk.transactions.getById(
            payment.transaction_id,
          );
          if (transaction.id !== payment.transaction_id)
            throw new BillingError("BILLING_TRANSACTION_INVALID", 503);
          this.checkTransaction(transaction, payment.subscription_id);
          await client.query("BEGIN");
          try {
            await this.lock(client, payment.researcher_id);
            await this.projectTransaction(client, transaction);
            await client.query("COMMIT");
          } catch (error) {
            await client.query("ROLLBACK");
            throw error;
          }
        })
        .catch(() => undefined);
    }
  }
}
