import type { PoolClient } from "pg";

// Called inside the existing credential mutation transaction. Removing consent
// also prevents a concurrently issued token from becoming usable again later.
export async function revokeResearcherMcpAccess(client: PoolClient, researcherId: string): Promise<void> {
  await client.query('DELETE FROM auth."oauthAccessToken" WHERE "userId" = $1', [researcherId]);
  await client.query('DELETE FROM auth."oauthRefreshToken" WHERE "userId" = $1', [researcherId]);
  await client.query('DELETE FROM auth."oauthConsent" WHERE "userId" = $1', [researcherId]);
  await client.query(`DELETE FROM auth."verification" WHERE
    CASE WHEN value IS JSON OBJECT THEN value::jsonb ELSE '{}'::jsonb END
      @> jsonb_build_object('type', 'authorization_code', 'userId', $1::text)`, [researcherId]);
}
