import { readFile } from 'node:fs/promises';
import { Pool } from 'pg';
import { afterAll, beforeEach, describe, expect, it } from 'vitest';
import { assertExactCatalog, collectAuthSchemaCatalog, type AuthSchemaCatalog } from './schema-contract.js';
import { AUTH_REFRESH_SOURCE, AUTH_REFRESH_TARGET, migrateUnifiedRefreshProofs } from './unified-refresh-migration.js';

const pool = new Pool({ connectionString: process.env.THESISTRACE_AUTH_TEST_OWNER_DATABASE_URL });
describe.sequential('Explicit unified refresh proof upgrade', () => {
  beforeEach(async () => {
    await pool.query('DROP SCHEMA IF EXISTS auth CASCADE');
    await pool.query('DROP SCHEMA IF EXISTS thesistrace_auth_migrations CASCADE');
    await pool.query('CREATE SCHEMA auth AUTHORIZATION thesistrace_owner');
    await pool.query(await readFile(new URL('../schema/migrations/0002-source-schema.sql', import.meta.url),'utf8'));
    await pool.query('INSERT INTO auth.schema_contract(singleton,schema_fingerprint) VALUES(TRUE,$1)',[AUTH_REFRESH_TARGET]);
    const source = JSON.parse(await readFile(new URL('../schema/migrations/0001-source-catalog.json', import.meta.url), 'utf8')) as AuthSchemaCatalog;
    const constraint = source.constraints.find(item => item.name === 'operator_proof_operation_check')!;
    await pool.query('ALTER TABLE auth.operator_proof DROP CONSTRAINT operator_proof_operation_check');
    await pool.query(`ALTER TABLE auth.operator_proof ADD CONSTRAINT operator_proof_operation_check ${constraint.definition}`);
    await pool.query('UPDATE auth.schema_contract SET schema_fingerprint=$1', [AUTH_REFRESH_SOURCE]);
    await pool.query(`INSERT INTO auth."user" (id,name,email,"emailVerified","createdAt","updatedAt",active)
      VALUES ('00000000-0000-4000-8000-000000000001','Preserved','preserved@example.com',TRUE,now(),now(),TRUE)`);
  });
  afterAll(async () => {
    await pool.query('DROP SCHEMA IF EXISTS auth CASCADE');
    await pool.query('DROP SCHEMA IF EXISTS thesistrace_auth_migrations CASCADE');
    await pool.end();
  });
  it('preserves existing records, admits dataset proofs and verifies repeat application', async () => {
    const before = (await pool.query('SELECT * FROM auth."user"')).rows;
    expect((await migrateUnifiedRefreshProofs(pool)).status).toBe('validated');
    expect((await migrateUnifiedRefreshProofs(pool, true)).status).toBe('applied');
    const target = JSON.parse(await readFile(new URL('../schema/migrations/0002-source-catalog.json', import.meta.url), 'utf8')) as AuthSchemaCatalog;
    assertExactCatalog(target, await collectAuthSchemaCatalog(pool));
    expect((await migrateUnifiedRefreshProofs(pool, true)).status).toBe('already_current');
    expect((await pool.query('SELECT * FROM auth."user"')).rows).toEqual(before);
    expect((await pool.query('SELECT target_fingerprint FROM thesistrace_auth_migrations.history')).rows).toEqual([{target_fingerprint: AUTH_REFRESH_TARGET}]);
  });
  it('rolls back the constraint and fingerprint after a late receipt failure', async () => {
    await pool.query('CREATE SCHEMA thesistrace_auth_migrations');
    await pool.query(`CREATE TABLE thesistrace_auth_migrations.history (
      id text PRIMARY KEY CHECK (false),source_fingerprint text,target_fingerprint text)`);
    await expect(migrateUnifiedRefreshProofs(pool, true)).rejects.toThrow();
    expect((await pool.query('SELECT schema_fingerprint FROM auth.schema_contract')).rows).toEqual([{schema_fingerprint: AUTH_REFRESH_SOURCE}]);
    expect((await migrateUnifiedRefreshProofs(pool)).status).toBe('validated');
    expect((await pool.query('SELECT email FROM auth."user"')).rows).toEqual([{email:'preserved@example.com'}]);
  });
});
