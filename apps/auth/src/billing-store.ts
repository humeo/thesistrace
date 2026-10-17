import { createHash } from "node:crypto";
import type { Pool } from "pg";
import { effectivePlan, type PaidEntitlement } from "./billing-entitlements.js";
import type { PlanKey } from "./quota-policy.js";

/** Auth owns paid rights; execution services own consumption. */
export async function researcherPlan(
  pool: Pick<Pool, "query">,
  researcherId: string,
  now = new Date(),
): Promise<PlanKey> {
  return effectivePlan(await paidEntitlements(pool, researcherId, now), now);
}
export async function paidEntitlements(
  pool: Pick<Pool, "query">,
  researcherId: string,
  now: Date,
): Promise<readonly PaidEntitlement[]> {
  const result = await pool.query<PaidEntitlement>(
    `
    SELECT plan_key AS plan, starts_at AS "startsAt", ends_at AS "endsAt",
           amount, refunded_amount AS refunded, disputed
    FROM auth.billing_payment WHERE researcher_id = $1 AND ends_at > $2
  `,
    [researcherId, now],
  );
  return result.rows;
}

export async function recordBillingReview(
  pool: Pick<Pool, "query">,
  id: string,
  type: string,
  payload: unknown,
) {
  const raw = JSON.stringify(payload);
  await pool.query(
    "INSERT INTO auth.billing_event(id,event_type,raw_body,body_sha256,processed_at) VALUES($1,$2,$3,$4,now())",
    [id, type, raw, createHash("sha256").update(raw).digest()],
  );
}
