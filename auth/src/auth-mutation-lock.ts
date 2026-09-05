import type { PoolClient } from "pg";

const authMutationLockKey = "thesistrace:auth-mutation";

export async function lockAuthMutationExclusive(
  client: PoolClient,
): Promise<void> {
  await client.query(
    "SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended($1, 0))",
    [authMutationLockKey],
  );
}

export async function lockAuthMutationShared(
  client: PoolClient,
): Promise<void> {
  await client.query(
    "SELECT pg_catalog.pg_advisory_xact_lock_shared(pg_catalog.hashtextextended($1, 0))",
    [authMutationLockKey],
  );
}

export async function lockAuthMutationSharedSession(
  client: PoolClient,
): Promise<void> {
  await client.query(
    "SELECT pg_catalog.pg_advisory_lock_shared(pg_catalog.hashtextextended($1, 0))",
    [authMutationLockKey],
  );
}

export async function unlockAuthMutationSharedSession(
  client: PoolClient,
): Promise<boolean> {
  const result = await client.query<{ unlocked: boolean }>(
    "SELECT pg_catalog.pg_advisory_unlock_shared(pg_catalog.hashtextextended($1, 0)) AS unlocked",
    [authMutationLockKey],
  );
  return result.rows[0]?.unlocked === true;
}
