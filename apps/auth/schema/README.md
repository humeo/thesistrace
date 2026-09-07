# Auth schema snapshot

`schema.sql` starts from the SQL emitted by the fixed Better Auth CLI and is
then normalized for ThesisTrace's dedicated `auth` PostgreSQL schema. The
normalization adds explicit schema qualification, stable constraint names, the
canonical-email database constraint, and the repository-owned
`schema_contract` table; it does not add an ORM or a runtime migration path.

Generate the upstream preview only against an empty disposable PostgreSQL
database:

```sh
THESISTRACE_SCHEMA_GENERATION_DATABASE_URL='postgresql://schema_generator:password@127.0.0.1:5432/disposable' \
  pnpm dlx auth@1.7.2 generate \
  --config apps/auth/schema.config.ts \
  --adapter kysely \
  --dialect postgresql \
  --output /tmp/thesistrace-better-auth.sql \
  --yes
```

`catalog-contract.json` is the reviewed PostgreSQL 16.10 `pg_catalog`
contract, including schema/relation ownership, relation durability, and RLS
state. The initializer may install `schema.sql` only when the `auth` scope is
absent or empty. Every populated scope is verified exactly and never migrated.
