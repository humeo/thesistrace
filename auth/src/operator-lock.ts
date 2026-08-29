import type { PoolClient } from "pg";

export const operatorAssignmentLockKey = "thesistrace:operator-assignment";

export async function lockOperatorAssignment(
  client: PoolClient,
): Promise<void> {
  await client.query(
    "SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended($1, 0))",
    [operatorAssignmentLockKey],
  );
}
