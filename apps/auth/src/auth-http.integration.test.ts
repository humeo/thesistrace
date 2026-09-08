import { createPublicKey, verify } from "node:crypto";

import { Pool } from "pg";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";

import { ResearcherAccessService } from "./access.js";
import { createAuthApp } from "./app.js";
import {
  createThesisTraceAuth,
  type AuthLifecycleDependencies,
} from "./auth.js";
import { AuthEventRecorder } from "./auth-events.js";
import { AuthBackgroundTasks } from "./background-tasks.js";
import { authTestSettings } from "../test-fixtures/auth-settings.js";
import {
  AuthOperationCoordinator,
  CredentialOperationCoordinator,
} from "./coordination.js";
import { createAuthCoordinationPool, createAuthPool } from "./database.js";
import { InvitationRejectedError } from "./invitation.js";
import { OperatorAssignmentService } from "./operator-assignment.js";
import { OperatorDirectoryService } from "./operator-directory.js";
import { OperatorProofService } from "./operator-proof.js";
import { OperatorSessionRevocationService } from "./operator-session-revocation.js";
import { checkAuthReadiness } from "./readiness.js";
import { initializeAuthSchema } from "./schema-initialize.js";
import { verifyAuthSchema } from "./schema-contract.js";
import { InvitationAdmission } from "./invitation-admission.js";
import { createMcpAccessTokenIssuer } from "./mcp-access-token.js";
import { unknownEmailHmac } from "./security.js";

const ownerDatabaseUrl = process.env.THESISTRACE_AUTH_TEST_OWNER_DATABASE_URL;
if (ownerDatabaseUrl === undefined) {
  throw new Error("THESISTRACE_AUTH_TEST_OWNER_DATABASE_URL is required");
}

const authRuntimeDatabaseUrl = roleDatabaseUrl(
  ownerDatabaseUrl,
  "auth_runtime",
  "auth-test-password",
);
const owner = new Pool({ connectionString: ownerDatabaseUrl, max: 2 });
const runtimePool = createAuthPool(authRuntimeDatabaseUrl);
const coordinationPool = createAuthCoordinationPool(authRuntimeDatabaseUrl);
const settings = authTestSettings({ databaseUrl: authRuntimeDatabaseUrl });
const invitationAdmission = new InvitationAdmission();
const credentialCoordinator = new CredentialOperationCoordinator({
  authSecret: settings.secret,
  coordination: new AuthOperationCoordinator(coordinationPool),
  pool: runtimePool,
});
const runtimeTasks = new Set<AuthBackgroundTasks>();
const authLifecycle: AuthLifecycleDependencies = {
  backgroundTask(promise) {
    void promise.catch(() => undefined);
  },
  invitationAdmission,
  async isResearcherActive(userId) {
    const result = await runtimePool.query<{ active: boolean }>(
      'SELECT active FROM auth."user" WHERE id = $1',
      [userId],
    );
    return result.rows[0]?.active === true;
  },
  recordPasswordResetCredential:
    credentialCoordinator.recordPasswordResetCredential,
  recordSession: credentialCoordinator.recordSession,
  async sendResetPassword() {},
};
const ambientOverrideNames = [
  "BETTER_AUTH_SECRETS",
  "BETTER_AUTH_TELEMETRY",
  "BETTER_AUTH_TELEMETRY_DEBUG",
  "BETTER_AUTH_TELEMETRY_ENDPOINT",
  "BETTER_AUTH_TELEMETRY_ID",
  "BETTER_AUTH_TRUSTED_ORIGINS",
] as const;
const originalOverrides = new Map(
  ambientOverrideNames.map((name) => [name, process.env[name]]),
);

describe.sequential("Auth database-backed HTTP contract", () => {
  beforeAll(async () => {
    for (const name of ambientOverrideNames) {
      delete process.env[name];
    }
    await owner.query("DROP SCHEMA IF EXISTS auth CASCADE");
    await initializeAuthSchema(owner);
  });

  beforeEach(async () => {
    await Promise.all([...runtimeTasks].map((tasks) => tasks.drain()));
    runtimeTasks.clear();
    await owner.query(`
      TRUNCATE
        auth.operator_assignment,
        auth.security_audit,
        auth.password_reset,
        auth.researcher_invitation,
        auth."verification",
        auth."rateLimit",
        auth."user"
      CASCADE
    `);
  });

  afterAll(async () => {
    await Promise.all([...runtimeTasks].map((tasks) => tasks.drain()));
    runtimeTasks.clear();
    await coordinationPool.end();
    await runtimePool.end();
    await owner.query("DROP SCHEMA IF EXISTS auth CASCADE");
    await owner.end();
    for (const name of ambientOverrideNames) {
      const original = originalOverrides.get(name);
      if (original === undefined) {
        delete process.env[name];
      } else {
        process.env[name] = original;
      }
    }
  });

  it("serves Better Auth ok through Hono against the initialized database", async () => {
    const { app } = runtime();
    const response = await app.request(`${settings.publicOrigin}/api/auth/ok`);

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ ok: true });
  });

  it("verifies a valid Session from PostgreSQL without refreshing its Cookie", async () => {
    const { app, auth } = runtime();
    const cookie = await createSessionCookie(auth, "valid@example.com");
    await owner.query(`
      UPDATE auth."session"
      SET
        "expiresAt" = CURRENT_TIMESTAMP + INTERVAL '4 days',
        "updatedAt" = CURRENT_TIMESTAMP - INTERVAL '3 days'
    `);
    const before = await persistedSessionTimes();

    const response = await app.request(
      `${settings.publicOrigin}/internal/session/verify`,
      { method: "POST", headers: { cookie } },
    );

    expect(response.status).toBe(200);
    expect(response.headers.has("set-cookie")).toBe(false);
    expect(await response.json()).toMatchObject({
      active: true,
      display_label: "valid",
      email: "valid@example.com",
      researcher_id: expect.stringMatching(
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
      ),
    });
    expect(await persistedSessionTimes()).toEqual(before);
  });

  it("serves Operator reads while every ordinary boundary remains an empty 404", async () => {
    const { app, auth } = runtime();
    const operatorCookie = await createSessionCookie(
      auth,
      "operator-http@example.com",
      "192.0.2.101",
    );
    const operator = await persistedPrincipal("operator-http@example.com");
    await new OperatorAssignmentService({ pool: runtimePool }).assign({
      researcherId: operator.researcherId,
    });
    const ordinaryCookie = await createSessionCookie(
      auth,
      "ordinary-http@example.com",
      "192.0.2.102",
    );

    const capability = await app.request(
      `${settings.publicOrigin}/api/auth/operator/capability`,
      { headers: { cookie: operatorCookie } },
    );
    expect(capability.status).toBe(200);
    expect(await capability.json()).toEqual({ operator: true });
    expect((await app.request(
      `${settings.publicOrigin}/internal/operator/page-access`,
      { headers: { cookie: operatorCookie } },
    )).status).toBe(204);
    const researchers = await app.request(
      `${settings.publicOrigin}/api/auth/operator/researchers?search=operator-http`,
      { headers: { cookie: operatorCookie } },
    );
    expect(researchers.status).toBe(200);
    expect(await researchers.json()).toMatchObject({
      items: [{
        active: true,
        current_session_count: 1,
        display_label: "operator-http",
        effective_invitation: null,
        email: "operator-http@example.com",
        researcher_id: operator.researcherId,
      }],
      next_cursor: null,
    });

    for (const path of [
      "/internal/operator/page-access",
      "/api/auth/operator/capability",
      "/api/auth/operator/researchers?cursor=canary",
      "/api/auth/operator/invitations",
    ]) {
      const response = await app.request(`${settings.publicOrigin}${path}`, {
        headers: { cookie: ordinaryCookie },
      });
      expect(response.status).toBe(404);
      expect(await response.text()).toBe("");
    }
  });

  it("revokes another Researcher's real Sessions while preserving Operator access", async () => {
    const { app, auth } = runtime();
    const operatorCookie = await createSessionCookie(
      auth,
      "operator-revoke@example.com",
      "192.0.2.111",
    );
    const operator = await persistedPrincipal("operator-revoke@example.com");
    await new OperatorAssignmentService({ pool: runtimePool }).assign({
      researcherId: operator.researcherId,
    });
    const targetCookie = await createSessionCookie(
      auth,
      "target-revoke@example.com",
      "192.0.2.112",
    );
    const target = await persistedPrincipal("target-revoke@example.com");
    const targetSecondSignIn = await app.request(
      `${settings.publicOrigin}/api/auth/sign-in/email-otp`,
      {
        body: JSON.stringify({
          email: "target-revoke@example.com",
          otp: await auth.api.createVerificationOTP({body:{email:"target-revoke@example.com",type:"sign-in"}}),
        }),
        headers: {
          "content-type": "application/json",
          origin: settings.publicOrigin,
          "x-thesistrace-client-ip": "192.0.2.113",
        },
        method: "POST",
      },
    );
    const targetSecondCookie = targetSecondSignIn.headers.get("set-cookie") ?? "";
    const ordinaryCookie = await createSessionCookie(
      auth,
      "ordinary-revoke@example.com",
      "192.0.2.114",
    );
    expect(targetSecondSignIn.status).toBe(200);

    const confirmation = await app.request(
      `${settings.publicOrigin}/api/auth/operator/proofs`,
      {
        body: JSON.stringify({
          operation: "researcher.sessions.revoke",
          otp: "123456",
          researcher_id: target.researcherId,
        }),
        headers: {
          "content-type": "application/json",
          cookie: operatorCookie,
          origin: settings.publicOrigin,
        },
        method: "POST",
      },
    );
    expect(confirmation.status).toBe(200);
    const proof = (await confirmation.json()) as { proof: string };
    const revoked = await app.request(
      `${settings.publicOrigin}/api/auth/operator/researchers/sessions/revoke`,
      {
        body: JSON.stringify({
          proof: proof.proof,
          researcher_id: target.researcherId,
        }),
        headers: {
          "content-type": "application/json",
          cookie: operatorCookie,
          origin: settings.publicOrigin,
        },
        method: "POST",
      },
    );

    expect(revoked.status).toBe(200);
    expect(await revoked.json()).toEqual({
      researcher_id: target.researcherId,
      revoked_session_count: 2,
      status: "updated",
    });
    for (const cookie of [targetCookie, targetSecondCookie]) {
      const response = await app.request(
        `${settings.publicOrigin}/internal/session/verify`,
        { headers: { cookie }, method: "POST" },
      );
      expect(response.status).toBe(401);
    }
    expect((await app.request(
      `${settings.publicOrigin}/api/auth/operator/capability`,
      { headers: { cookie: operatorCookie } },
    )).status).toBe(200);

    const selfConfirmation = await app.request(
      `${settings.publicOrigin}/api/auth/operator/proofs`,
      {
        body: JSON.stringify({
          operation: "researcher.sessions.revoke",
          otp: "123456",
          researcher_id: operator.researcherId,
        }),
        headers: {
          "content-type": "application/json",
          cookie: operatorCookie,
          origin: settings.publicOrigin,
        },
        method: "POST",
      },
    );
    const selfProof = (await selfConfirmation.json()) as { proof: string };
    const protectedResponse = await app.request(
      `${settings.publicOrigin}/api/auth/operator/researchers/sessions/revoke`,
      {
        body: JSON.stringify({
          proof: selfProof.proof,
          researcher_id: operator.researcherId,
        }),
        headers: {
          "content-type": "application/json",
          cookie: operatorCookie,
          origin: settings.publicOrigin,
        },
        method: "POST",
      },
    );
    expect(protectedResponse.status).toBe(409);
    expect((await owner.query<{ count: string }>(
      'SELECT count(*) FROM auth."session" WHERE "userId" = $1',
      [operator.researcherId],
    )).rows).toEqual([{ count: "1" }]);

    const denied = await app.request(
      `${settings.publicOrigin}/api/auth/operator/researchers/sessions/revoke`,
      {
        body: JSON.stringify({}),
        headers: {
          "content-type": "application/json",
          cookie: ordinaryCookie,
          origin: "https://attacker.example",
        },
        method: "POST",
      },
    );
    expect(denied.status).toBe(404);
    expect(await denied.text()).toBe("");
  });

  it("revokes the Session produced by an already-running HTTP sign-in", async () => {
    const { app, auth } = runtime();
    const operatorCookie = await createSessionCookie(
      auth,
      "operator-linearized-revoke@example.com",
      "192.0.2.115",
    );
    const operator = await persistedPrincipal(
      "operator-linearized-revoke@example.com",
    );
    await new OperatorAssignmentService({ pool: runtimePool }).assign({
      researcherId: operator.researcherId,
    });
    await createSessionCookie(
      auth,
      "target-linearized-revoke@example.com",
      "192.0.2.116",
    );
    const target = await persistedPrincipal(
      "target-linearized-revoke@example.com",
    );
    await owner.query('DELETE FROM auth."session" WHERE "userId" = $1', [
      target.researcherId,
    ]);
    const confirmation = await app.request(
      `${settings.publicOrigin}/api/auth/operator/proofs`,
      {
        body: JSON.stringify({
          operation: "researcher.sessions.revoke",
          otp: "123456",
          researcher_id: target.researcherId,
        }),
        headers: {
          "content-type": "application/json",
          cookie: operatorCookie,
          origin: settings.publicOrigin,
        },
        method: "POST",
      },
    );
    expect(confirmation.status).toBe(200);
    const proof = (await confirmation.json()) as { proof: string };
    const blocker = await owner.connect();
    const insertHoldKey = "operator-revoke-sign-in-insert-hold";
    let signingIn: Promise<Response> | undefined;
    let revoking: Promise<Response> | undefined;
    try {
      await blocker.query(
        "SELECT pg_catalog.pg_advisory_lock(pg_catalog.hashtextextended($1, 0))",
        [insertHoldKey],
      );
      await owner.query(`
        CREATE FUNCTION auth.test_hold_operator_revoke_session_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $function$
        BEGIN
          PERFORM pg_catalog.pg_advisory_xact_lock(
            pg_catalog.hashtextextended('${insertHoldKey}', 0)
          );
          RETURN NEW;
        END;
        $function$;
        CREATE TRIGGER test_hold_operator_revoke_session_insert
        BEFORE INSERT ON auth."session"
        FOR EACH ROW
        EXECUTE FUNCTION auth.test_hold_operator_revoke_session_insert()
      `);

      const startedSignIn = Promise.resolve(app.request(
        `${settings.publicOrigin}/api/auth/sign-in/email-otp`,
        {
          body: JSON.stringify({
            email: "target-linearized-revoke@example.com",
            otp: await auth.api.createVerificationOTP({body:{email:"target-linearized-revoke@example.com",type:"sign-in"}}),
          }),
          headers: {
            "content-type": "application/json",
            origin: settings.publicOrigin,
            "x-thesistrace-client-ip": "192.0.2.117",
          },
          method: "POST",
        },
      ));
      signingIn = startedSignIn;
      void startedSignIn.catch(() => undefined);
      await waitForCondition(() => hasAdvisoryWaiter("thesistrace_auth"));

      const startedRevocation = Promise.resolve(app.request(
        `${settings.publicOrigin}/api/auth/operator/researchers/sessions/revoke`,
        {
          body: JSON.stringify({
            proof: proof.proof,
            researcher_id: target.researcherId,
          }),
          headers: {
            "content-type": "application/json",
            cookie: operatorCookie,
            origin: settings.publicOrigin,
          },
          method: "POST",
        },
      ));
      revoking = startedRevocation;
      void startedRevocation.catch(() => undefined);
      await waitForCondition(async () => {
        const result = await owner.query<{ state: string }>(
          "SELECT state FROM auth.operator_proof",
        );
        return result.rows[0]?.state === "claimed";
      });

      await blocker.query(
        "SELECT pg_catalog.pg_advisory_unlock(pg_catalog.hashtextextended($1, 0))",
        [insertHoldKey],
      );
      const [signInResponse, revocationResponse] = await Promise.all([
        startedSignIn,
        startedRevocation,
      ]);
      const targetCookie = signInResponse.headers.get("set-cookie") ?? "";

      expect(signInResponse.status).toBe(200);
      expect(revocationResponse.status).toBe(200);
      expect(await revocationResponse.json()).toEqual({
        researcher_id: target.researcherId,
        revoked_session_count: 1,
        status: "updated",
      });
      expect((await app.request(
        `${settings.publicOrigin}/internal/session/verify`,
        { headers: { cookie: targetCookie }, method: "POST" },
      )).status).toBe(401);
      expect((await app.request(
        `${settings.publicOrigin}/api/auth/operator/capability`,
        { headers: { cookie: operatorCookie } },
      )).status).toBe(200);
    } finally {
      await blocker
        .query(
          "SELECT pg_catalog.pg_advisory_unlock(pg_catalog.hashtextextended($1, 0))",
          [insertHoldKey],
        )
        .catch(() => undefined);
      blocker.release();
      await Promise.allSettled([
        signingIn ?? Promise.resolve(),
        revoking ?? Promise.resolve(),
      ]);
      await owner.query(`
        DROP TRIGGER IF EXISTS test_hold_operator_revoke_session_insert
          ON auth."session";
        DROP FUNCTION IF EXISTS auth.test_hold_operator_revoke_session_insert()
      `);
    }
  });

  it("exchanges an active database Session for a short-lived Core-verifiable MCP token", async () => {
    const { app, auth } = runtime();
    const cookie = await createSessionCookie(auth, "agent@example.com");
    const before = await persistedSessionTimes();

    const response = await app.request(
      `${settings.publicOrigin}/internal/session/exchange`,
      { method: "POST", headers: { cookie } },
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(response.headers.has("set-cookie")).toBe(false);
    const body = await response.json() as {
      access_token: string;
      expires_in: number;
      token_type: string;
    };
    expect(body).toMatchObject({
      expires_in: settings.mcpTokenLifetimeSeconds,
      token_type: "Bearer",
    });
    const [encodedHeader, encodedPayload, encodedSignature] =
      body.access_token.split(".");
    expect(encodedHeader).toBeDefined();
    expect(encodedPayload).toBeDefined();
    expect(encodedSignature).toBeDefined();
    const header = decodeJwtSegment(encodedHeader ?? "");
    const claims = decodeJwtSegment(encodedPayload ?? "");
    expect(header).toEqual({ alg: "EdDSA", kid: settings.mcpPublicJwk.kid });
    expect(claims).toMatchObject({
      aud: settings.mcpAudience,
      client_id: settings.mcpClientId,
      iss: settings.mcpIssuer,
      scope: settings.mcpGrantScopes.join(" "),
      sub: expect.stringMatching(
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
      ),
    });
    expect(claims).toMatchObject({
      exp: expect.any(Number),
      iat: expect.any(Number),
      jti: expect.stringMatching(
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
      ),
      nbf: expect.any(Number),
    });
    expect(claims.scope).not.toContain("refresh");
    expect(
      verify(
        null,
        Buffer.from(`${encodedHeader}.${encodedPayload}`),
        createPublicKey({ format: "jwk", key: settings.mcpPublicJwk }),
        Buffer.from(encodedSignature ?? "", "base64url"),
      ),
    ).toBe(true);
    expect(await persistedSessionTimes()).toEqual(before);
  });

  it("trims and lowercases email at the public email-OTP boundary", async () => {
    const { app, auth } = runtime();
    await createSessionCookie(auth, "canonical@example.com");

    const response = await app.request(
      `${settings.publicOrigin}/api/auth/sign-in/email-otp`,
      {
        body: JSON.stringify({
          email: "  Canonical@Example.COM  ",
          otp: await auth.api.createVerificationOTP({body:{email:"canonical@example.com",type:"sign-in"}}),
        }),
        headers: {
          "content-type": "application/json",
          origin: settings.publicOrigin,
        },
        method: "POST",
      },
    );

    const users = await owner.query<{ email: string }>('SELECT email FROM auth."user"');
    expect(response.status).toBe(200);
    expect(users.rows).toEqual([{ email: "canonical@example.com" }]);
  });

  it("rejects a cross-origin credential request", async () => {
    const { app, auth } = runtime();
    await createSessionCookie(auth, "origin@example.com");

    const response = await app.request(
      `${settings.publicOrigin}/api/auth/sign-in/email-otp`,
      {
        body: JSON.stringify({
          email: "origin@example.com",
          otp: await auth.api.createVerificationOTP({body:{email:"origin@example.com",type:"sign-in"}}),
        }),
        headers: {
          "content-type": "application/json",
          origin: "https://attacker.example",
        },
        method: "POST",
      },
    );

    expect(response.status).toBe(403);
  });

  it.each([11, 129])("rejects a %i-character password", async (length) => {
    const { auth } = runtime();
    const response = await directSignUp(auth, {
      email: `password-${length}@example.com`,
      password: "x".repeat(length),
    });

    expect(response.status).toBe(400);
    expect(
      await owner.query<{ count: string }>('SELECT count(*) FROM auth."user"'),
    ).toMatchObject({ rows: [{ count: "0" }] });
  });

  it("enforces the sign-in rate limit in PostgreSQL", async () => {
    const { app } = runtime();
    const statuses: number[] = [];
    for (let attempt = 0; attempt < 6; attempt += 1) {
      const response = await app.request(
        `${settings.publicOrigin}/api/auth/sign-in/email-otp`,
        {
          body: JSON.stringify({
            email: "missing@example.com",
            otp: "000000",
          }),
          headers: {
            "content-type": "application/json",
            origin: settings.publicOrigin,
            "x-thesistrace-client-ip": "192.0.2.10",
          },
          method: "POST",
        },
      );
      statuses.push(response.status);
    }

    expect(statuses.slice(0, 5)).not.toContain(429);
    expect(statuses[5]).toBe(429);
    const records = await owner.query<{ count: string }>(
      'SELECT count(*) FROM auth."rateLimit"',
    );
    expect(records.rows).toEqual([{ count: "1" }]);
  });

  it("audits known and unknown sign-in outcomes without raw unknown email", async () => {
    const { app, auth, tasks } = runtime();
    await createSessionCookie(auth, "audit@example.com");

    const knownFailure = await app.request(
      `${settings.publicOrigin}/api/auth/sign-in/email-otp`,
      {
        body: JSON.stringify({
          email: "audit@example.com",
          otp: "000000",
        }),
        headers: {
          "content-type": "application/json",
          origin: settings.publicOrigin,
        },
        method: "POST",
      },
    );
    const knownSuccess = await app.request(
      `${settings.publicOrigin}/api/auth/sign-in/email-otp`,
      {
        body: JSON.stringify({
          email: "audit@example.com",
          otp: await auth.api.createVerificationOTP({body:{email:"audit@example.com",type:"sign-in"}}),
        }),
        headers: {
          "content-type": "application/json",
          origin: settings.publicOrigin,
        },
        method: "POST",
      },
    );
    await app.request(`${settings.publicOrigin}/api/auth/sign-in/email-otp`, {
      body: JSON.stringify({
        email: "unknown-audit@example.com",
        otp: "000000",
      }),
      headers: {
        "content-type": "application/json",
        origin: settings.publicOrigin,
      },
      method: "POST",
    });
    await tasks.drain();
    const audits = await owner.query<{
      outcome: string;
      researcher_id: string | null;
      unknown_email_hmac: Buffer | null;
    }>(`
      SELECT outcome, researcher_id, unknown_email_hmac
      FROM auth.security_audit
      WHERE event IN ('sign_in_succeeded', 'sign_in_failed')
    `);

    expect(knownFailure.status).not.toBe(200);
    expect(knownSuccess.status).toBe(200);
    expect(audits.rows).toHaveLength(3);
    expect(audits.rows).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ outcome: "failed", researcher_id: expect.any(String) }),
        expect.objectContaining({
          outcome: "succeeded",
          researcher_id: expect.any(String),
        }),
        {
          outcome: "failed",
          researcher_id: null,
          unknown_email_hmac: unknownEmailHmac(
            settings.secret,
            "unknown-audit@example.com",
          ),
        },
      ]),
    );
    expect(JSON.stringify(audits.rows)).not.toContain("unknown-audit@example.com");
  });

  it("audits logout and revokes only its current Session", async () => {
    const {app,auth,tasks} = runtime();
    const cookie = await createSessionCookie(auth, "logout@example.com");
    const response = await app.request(`${settings.publicOrigin}/api/auth/sign-out`, {method:"POST",headers:{cookie,origin:settings.publicOrigin}});
    expect(response.status).toBe(200); await tasks.drain();
    expect((await owner.query('SELECT count(*) FROM auth."session"')).rows[0].count).toBe("0");
    expect((await owner.query("SELECT event,outcome FROM auth.security_audit WHERE event='sessions_revoked'")).rows).toContainEqual({event:"sessions_revoked",outcome:"succeeded"});
  });

  it("never turns a committed sign-in or sign-out into an audit 503", async () => {
    const { app, auth, tasks } = runtime();
    const originalCookie = await createSessionCookie(
      auth,
      "audit-unavailable@example.com",
    );
    const whileAuditUnavailable = async (
      operation: () => Promise<Response>,
    ): Promise<Response> => {
      const blocker = await owner.connect();
      let response: Response;
      try {
        await blocker.query("BEGIN");
        await blocker.query("LOCK TABLE auth.security_audit IN ACCESS EXCLUSIVE MODE");
        response = await operation();
        // Password hashing may take longer on a busy host. The contract is that
        // HTTP completes while the real audit write is still blocked by the lock.
        let auditCompleted = false;
        const audit = tasks.drain().then(() => { auditCompleted = true; });
        await new Promise<void>((resolve) => setImmediate(resolve));
        expect(auditCompleted).toBe(false);
        await audit;
      } finally {
        await blocker.query("ROLLBACK").catch(() => undefined);
        blocker.release();
      }
      expect(response.status).toBe(200);
      return response;
    };

    const signedIn = await whileAuditUnavailable(async () =>
      Promise.resolve(app.request(`${settings.publicOrigin}/api/auth/sign-in/email-otp`, {
        body: JSON.stringify({
          email: "audit-unavailable@example.com",
          otp: await auth.api.createVerificationOTP({body:{email:"audit-unavailable@example.com",type:"sign-in"}}),
        }),
        headers: {
          "content-type": "application/json",
          origin: settings.publicOrigin,
        },
        method: "POST",
      })),
    );
    expect(signedIn.headers.get("set-cookie")).toContain("session_token=");

    await whileAuditUnavailable(async () =>
      Promise.resolve(app.request(`${settings.publicOrigin}/api/auth/sign-out`, {
        headers: { cookie: originalCookie, origin: settings.publicOrigin },
        method: "POST",
      })),
    );
    expect(
      await owner.query<{ count: string }>('SELECT count(*) FROM auth."session"'),
    ).toMatchObject({ rows: [{ count: "1" }] });
  });

  it("sets the complete Production Session Cookie attributes", async () => {
    const auth = createThesisTraceAuth(
      {
        ...settings,
        environment: "production",
        publicOrigin: "https://thesistrace.test",
        secret:
          "a4f781c2d6e9035b8a1f74c092e5bd3680c4f719a2e65b03d8f14c7a9e256bd0",
        secureCookies: true,
      },
      runtimePool,
      authLifecycle,
    );
    const response = await directSignUp(auth, {
      email: "cookie@example.com",
      origin: "https://thesistrace.test",
      password: "correct-horse-battery-staple",
      publicOrigin: "https://thesistrace.test",
    });
    const cookie = response.headers.get("set-cookie") ?? "";

    expect(response.status).toBe(200);
    expect(cookie).toContain("__Secure-thesistrace.session_token=");
    expect(cookie).toMatch(/; HttpOnly/i);
    expect(cookie).toMatch(/; SameSite=Lax/i);
    expect(cookie).toMatch(/; Secure/i);
  });

  it("refreshes an aged Session through the public get-session endpoint", async () => {
    const { app, auth } = runtime();
    const cookie = await createSessionCookie(auth, "rolling@example.com");
    await owner.query(`
      UPDATE auth."session"
      SET
        "expiresAt" = CURRENT_TIMESTAMP + INTERVAL '4 days',
        "updatedAt" = CURRENT_TIMESTAMP - INTERVAL '3 days'
    `);
    const before = await persistedSessionTimes();

    const response = await app.request(
      `${settings.publicOrigin}/api/auth/get-session`,
      { headers: { cookie } },
    );
    const after = await persistedSessionTimes();

    expect(response.status).toBe(200);
    expect(response.headers.has("set-cookie")).toBe(true);
    expect(after.updatedAt.getTime()).toBeGreaterThan(before.updatedAt.getTime());
    expect(after.expiresAt.getTime()).toBeGreaterThan(before.expiresAt.getTime());
  });

  it("keeps self-service display-label editing disabled", async () => {
    const { app, auth } = runtime();
    const cookie = await createSessionCookie(auth, "immutable@example.com");

    const response = await app.request(
      `${settings.publicOrigin}/api/auth/update-user`,
      {
        body: JSON.stringify({ name: "changed-by-user" }),
        headers: {
          "content-type": "application/json",
          cookie,
          origin: settings.publicOrigin,
        },
        method: "POST",
      },
    );
    const user = await owner.query<{ name: string }>('SELECT name FROM auth."user"');

    expect(response.status).toBe(404);
    expect(user.rows).toEqual([{ name: "immutable" }]);
  });

  it.each(["list-sessions", "update-session"])(
    "does not expose the %s Session-management endpoint",
    async (path) => {
      const { app, auth } = runtime();
      const cookie = await createSessionCookie(auth, `${path}@example.com`);

      const response = await app.request(
        `${settings.publicOrigin}/api/auth/${path}`,
        {
          body: JSON.stringify({}),
          headers: {
            "content-type": "application/json",
            cookie,
            origin: settings.publicOrigin,
          },
          method: "POST",
        },
      );

      expect(response.status).toBe(404);
      expect(await response.text()).toBe("");
    },
  );

  it.each([
    ["/internal/session/verify", "invalid"],
    ["/internal/session/verify", "expired"],
    ["/internal/session/verify", "revoked"],
    ["/internal/session/verify", "inactive"],
    ["/internal/session/exchange", "invalid"],
    ["/internal/session/exchange", "expired"],
    ["/internal/session/exchange", "revoked"],
    ["/internal/session/exchange", "inactive"],
  ])(
    "%s rejects an %s database Session",
    async (path, state) => {
      const { app, auth } = runtime();
      let cookie = "thesistrace.session_token=invalid";
      if (state !== "invalid") {
        cookie = await createSessionCookie(auth, `${state}@example.com`);
      }
      if (state === "expired") {
        await owner.query(
          `UPDATE auth."session" SET "expiresAt" = CURRENT_TIMESTAMP - INTERVAL '1 second'`,
        );
      } else if (state === "revoked") {
        await owner.query('DELETE FROM auth."session"');
      } else if (state === "inactive") {
        await owner.query('UPDATE auth."user" SET active = FALSE');
      }

      const response = await app.request(
        `${settings.publicOrigin}${path}`,
        { method: "POST", headers: { cookie } },
      );

      expect(response.status).toBe(401);
      expect(response.headers.has("set-cookie")).toBe(false);
      expect(await response.json()).toEqual({ code: "AUTHENTICATION_REQUIRED" });
    },
  );

  it("fails closed on malformed persisted identity state", async () => {
    const { app, auth } = runtime();
    const cookie = await createSessionCookie(auth, "malformed@example.com");
    await owner.query('UPDATE auth."user" SET name = \'\'');

    const response = await app.request(
      `${settings.publicOrigin}/internal/session/verify`,
      { method: "POST", headers: { cookie } },
    );

    expect(response.status).toBe(503);
    expect(response.headers.has("set-cookie")).toBe(false);
    expect(await response.json()).toEqual({ code: "AUTH_SERVICE_UNAVAILABLE" });
  });

  it("returns 503 within the database lock budget", async () => {
    const { app, auth } = runtime();
    const cookie = await createSessionCookie(auth, "locked@example.com");
    const blocker = await owner.connect();
    try {
      await blocker.query("BEGIN");
      await blocker.query('LOCK TABLE auth."session" IN ACCESS EXCLUSIVE MODE');
      const startedAt = performance.now();

      const response = await app.request(
        `${settings.publicOrigin}/internal/session/verify`,
        { method: "POST", headers: { cookie } },
      );

      expect(response.status).toBe(503);
      expect(performance.now() - startedAt).toBeLessThan(4_000);
    } finally {
      await blocker.query("ROLLBACK").catch(() => undefined);
      blocker.release();
    }
  });

  it("checks the exact startup schema and Session storage for readiness", async () => {
    await expect(verifyAuthSchema(runtimePool)).resolves.toBeUndefined();
    await expect(checkAuthReadiness(runtimePool)).resolves.toBe(true);

    await owner.query(
      "UPDATE auth.schema_contract SET schema_fingerprint = repeat('0', 64)",
    );
    await expect(checkAuthReadiness(runtimePool)).resolves.toBe(false);
  });
});

function runtime() {
  const auth = createThesisTraceAuth(settings, runtimePool, authLifecycle);
  const issueMcpAccessToken = createMcpAccessTokenIssuer(settings, {
    sign: (payload) => auth.api.signJWT({ body: { payload } }),
  });
  const tasks = new AuthBackgroundTasks();
  runtimeTasks.add(tasks);
  const events = new AuthEventRecorder({
    authSecret: settings.secret,
    backgroundTask: tasks.handler,
    pool: runtimePool,
  });
  const operatorDirectory = new OperatorDirectoryService({
    authSecret: settings.secret,
    pool: runtimePool,
  });
  const operatorProofs = new OperatorProofService({
    verifyCode: async (_principal, otp) => { if (otp !== "123456") throw new Error("invalid-test-code"); }, pool: runtimePool });
  const researcherAccess = new ResearcherAccessService({
    authSecret: settings.secret,
    credentialCoordinator,
    pool: runtimePool,
  });
  const operatorSessionRevocations = new OperatorSessionRevocationService({
    access: researcherAccess,
    proofs: operatorProofs,
  });
  const app = createAuthApp({
    async acceptInvitation() {
      throw new InvitationRejectedError();
    },
    authHandler: (request) =>
      credentialCoordinator.handleAuthRequest(
        request,
        (coordinated) =>
          events.handle(
            coordinated,
            (delegated) => auth.handler(delegated),
            (headers) =>
              auth.api.getSession({
                headers,
                query: { disableCookieCache: true, disableRefresh: true },
              }),
          ),
        (headers) =>
          auth.api.getSession({
            headers,
            query: { disableCookieCache: true, disableRefresh: true },
          }),
      ),
    confirmOperatorProof: (principal, input) =>
      operatorProofs.confirm(principal, input),
    consumeOperatorProof: async (principal, input) => {
      await operatorProofs.consumeExternal(principal, input);
    },
    async consumeInvitationRateLimit() {
      return { allowed: true, retryAfterSeconds: 0 };
    },

    async consumeOperatorProofRateLimit() {
      return { allowed: true, retryAfterSeconds: 0 };
    },
    getSession: (input) => auth.api.getSession(input),
    hasOperatorCapability: (principal) =>
      operatorDirectory.hasCapability(principal),
    async inspectInvitation() {
      throw new InvitationRejectedError();
    },
    async issueOperatorInvitation() {
      throw new Error("OPERATOR_MUTATION_UNAVAILABLE_IN_HTTP_CONTRACT_HARNESS");
    },
    listOperatorInvitations: (principal, input) =>
      operatorDirectory.listInvitations(principal, input),
    listOperatorResearchers: (principal, input) =>
      operatorDirectory.listResearchers(principal, input),
    issueMcpAccessToken,
    publicOrigin: settings.publicOrigin,
    readiness: () => checkAuthReadiness(runtimePool),
    async reissueOperatorInvitation() {
      throw new Error("OPERATOR_MUTATION_UNAVAILABLE_IN_HTTP_CONTRACT_HARNESS");
    },
    revokeOperatorResearcherSessions: (principal, input) =>
      operatorSessionRevocations.revoke(principal, input),

  });
  return { app, auth, tasks };
}

function decodeJwtSegment(value: string): Record<string, unknown> {
  return JSON.parse(Buffer.from(value, "base64url").toString("utf8")) as Record<
    string,
    unknown
  >;
}

async function createSessionCookie(
  auth: ReturnType<typeof createThesisTraceAuth>,
  email: string,
  clientIp?: string,
): Promise<string> {
  const response = await directSignUp(auth, {
    clientIp,
    email,
    password: "correct-horse-battery-staple",
  });
  expect(response.status).toBe(200);
  const setCookie = response.headers.get("set-cookie");
  expect(setCookie).not.toBeNull();
  return setCookie ?? "";
}

async function persistedPrincipal(email: string): Promise<Readonly<{
  researcherId: string;
  sessionId: string;
}>> {
  const result = await owner.query<{
    researcher_id: string;
    session_id: string;
  }>(
    `
      SELECT
        researcher.id AS researcher_id,
        login_session.id AS session_id
      FROM auth."user" AS researcher
      JOIN auth."session" AS login_session
        ON login_session."userId" = researcher.id
      WHERE researcher.email = $1
      ORDER BY login_session."createdAt" DESC, login_session.id DESC
      LIMIT 1
    `,
    [email],
  );
  const row = result.rows[0];
  if (row === undefined) throw new Error("expected persisted Auth principal");
  return { researcherId: row.researcher_id, sessionId: row.session_id };
}

async function directSignUp(
  auth: ReturnType<typeof createThesisTraceAuth>,
  input: Readonly<{
    clientIp?: string;
    email: string;
    origin?: string;
    password: string;
    publicOrigin?: string;
  }>,
): Promise<Response> {
  const publicOrigin = input.publicOrigin ?? settings.publicOrigin;
  return invitationAdmission.run(
    input.email.trim().toLowerCase(),
    () =>
      auth.handler(
        new Request(`${publicOrigin}/api/auth/sign-up/email`, {
          body: JSON.stringify({
            email: input.email,
            name: "client-supplied-label",
            password: input.password,
          }),
          headers: {
            "content-type": "application/json",
            origin: input.origin ?? settings.publicOrigin,
            "x-thesistrace-client-ip": input.clientIp ?? `192.0.2.${input.password.length}`,
          },
          method: "POST",
        }),
      ),
  );
}

async function persistedSessionTimes(): Promise<{
  expiresAt: Date;
  updatedAt: Date;
}> {
  const result = await owner.query<{ expiresAt: Date; updatedAt: Date }>(
    'SELECT "expiresAt", "updatedAt" FROM auth."session"',
  );
  const row = result.rows[0];
  if (row === undefined) {
    throw new Error("expected one persisted Session");
  }
  return row;
}

async function hasAdvisoryWaiter(applicationName: string): Promise<boolean> {
  const result = await owner.query<{ waiting: boolean }>(
    `
      SELECT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_stat_activity
        WHERE application_name = $1
          AND wait_event_type = 'Lock'
      ) AS waiting
    `,
    [applicationName],
  );
  return result.rows[0]?.waiting === true;
}

async function waitForCondition(
  condition: () => Promise<boolean>,
): Promise<void> {
  const deadline = performance.now() + 2_000;
  while (performance.now() < deadline) {
    if (await condition()) return;
    await new Promise<void>((resolve) => setTimeout(resolve, 10));
  }
  throw new Error("condition was not reached before its deadline");
}

function roleDatabaseUrl(base: string, username: string, password: string): string {
  const url = new URL(base);
  url.username = username;
  url.password = password;
  return url.toString();
}
