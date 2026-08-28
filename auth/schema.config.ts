import { Pool } from "pg";

import { createThesisTraceAuth } from "./src/auth.js";

const databaseUrl = process.env.THESISTRACE_SCHEMA_GENERATION_DATABASE_URL;
if (databaseUrl === undefined) {
  throw new Error("THESISTRACE_SCHEMA_GENERATION_DATABASE_URL is required");
}

const pool = new Pool({ connectionString: databaseUrl });

export const auth = createThesisTraceAuth(
  {
    databaseUrl,
    environment: "test",
    host: "127.0.0.1",
    port: 8200,
    publicOrigin: "http://127.0.0.1:5173",
    secret: "schema-generation-only-secret-000000000000000000",
    secureCookies: false,
  },
  pool,
);
