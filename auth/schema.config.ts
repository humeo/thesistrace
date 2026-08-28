import { Pool } from "pg";

import {
  createClosedAuthLifecycle,
  createThesisTraceAuth,
} from "./src/auth.js";

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
    resendApiKey: "schema-generation-only",
    resendApiUrl: "http://127.0.0.1:8300",
    resendFromEmail: "ThesisTrace <noreply@thesistrace.test>",
    secret: "schema-generation-only-secret-000000000000000000",
    secureCookies: false,
  },
  pool,
  createClosedAuthLifecycle(),
);
