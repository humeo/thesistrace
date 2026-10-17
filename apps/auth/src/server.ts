import { SignInCodeAdmission } from "./sign-in-code-admission.js";
import { researcherPlan } from "./billing-store.js";
import { createTurnstileVerifier } from "./turnstile.js";
import { OperatorEmailCode } from "./operator-email-code.js";
import { EmailCodeDelivery } from "./email-code.js";
import { serve } from "@hono/node-server";

import { isResearcherActive, ResearcherAccessService } from "./access.js";
import { createMcpConnectionsApp } from "./mcp-connections.js";
import { BillingService } from "./billing.js";
import { readBillingSettings } from "./billing-config.js";
import { createBillingApp } from "./billing-http.js";
import { createAuthApp, loadActiveSession } from "./app.js";
import { createThesisTraceAuth } from "./auth.js";
import { AuthEventRecorder } from "./auth-events.js";
import { AuthEndpointRateLimiter } from "./auth-rate-limit.js";
import { AuthBackgroundTasks } from "./background-tasks.js";
import { runAuthCleanup } from "./cleanup.js";
import { readAuthSettings } from "./config.js";
import {
  AuthOperationCoordinator,
  CredentialOperationCoordinator,
} from "./coordination.js";
import { createAuthCoordinationPool, createAuthPool } from "./database.js";
import { diagnoseAuthFailure } from "./failure.js";
import { createAuthHttpObserver } from "./http-observability.js";
import { createMcpAccessTokenIssuer } from "./mcp-access-token.js";
import { OperatorDirectoryService } from "./operator-directory.js";
import { OperatorProofService } from "./operator-proof.js";
import { OperatorSessionRevocationService } from "./operator-session-revocation.js";
import { checkAuthReadiness } from "./readiness.js";
import { sendResendEmail } from "./resend.js";
import { verifyAuthSchema } from "./schema-contract.js";
import { enforceAuthSecretContract } from "./secret-contract.js";

async function main(): Promise<void> {
  const settings = readAuthSettings();
  const pool = createAuthPool(settings.databaseUrl);
  const coordinationPool = createAuthCoordinationPool(settings.databaseUrl);
  const reportPoolError = (error: Error) => {
    process.stderr.write(
      `${JSON.stringify({
        code: "AUTH_DATABASE_UNAVAILABLE",
        event: "auth_database_pool_error",
        ...diagnoseAuthFailure(error),
      })}\n`,
    );
  };
  pool.on("error", reportPoolError);
  coordinationPool.on("error", reportPoolError);

  try {
    await verifyAuthSchema(pool);
    await enforceAuthSecretContract(pool, settings.secret);
    const backgroundTasks = new AuthBackgroundTasks(() => {
      process.stderr.write(
        `${JSON.stringify({
          code: "AUTH_BACKGROUND_TASK_FAILED",
          event: "auth_background_task_failed",
        })}\n`,
      );
    });
    const coordination = new AuthOperationCoordinator(coordinationPool);
    const credentialCoordinator = new CredentialOperationCoordinator({
      authSecret: settings.secret,
      coordination,
      pool,
    });
    const sendEmail = (email: Parameters<typeof sendResendEmail>[1]) =>
      sendResendEmail(
        {
          apiKey: settings.resendApiKey,
          apiUrl: settings.resendApiUrl,
          fromEmail: settings.resendFromEmail,
        },
        email,
      );
    const auth = createThesisTraceAuth(settings, pool, {
      backgroundTask: backgroundTasks.handler,
      isResearcherActive: (id) => isResearcherActive(pool, id),
      recordSession: credentialCoordinator.recordSession,
    });
    await auth.$context;
    const emailCodes = new EmailCodeDelivery({auth, coordinator: credentialCoordinator, sendEmail});
    const emailCodeRateLimiter = new AuthEndpointRateLimiter({authSecret: settings.secret, pool, scope: "email-code"});
    const signInAdmission = new SignInCodeAdmission({
      authSecret: settings.secret, pool,
      globalHourlyLimit: settings.emailCodeGlobalHourlyLimit,
      globalDailyLimit: settings.emailCodeGlobalDailyLimit,
      verifyChallenge: createTurnstileVerifier({secretKey: settings.turnstileSecretKey, publicOrigin: settings.publicOrigin, verifyUrl: settings.turnstileVerifyUrl}),
      onBudgetReached: (windowSeconds, limit) => process.stderr.write(JSON.stringify({event: "auth_email_code_budget_reached", window_seconds: windowSeconds, limit}) + "\n"),
    });
    const issueMcpAccessToken = createMcpAccessTokenIssuer(settings, {
      sign: (payload) => auth.api.signJWT({ body: { payload } }),
    });
    const operatorProofRateLimiter = new AuthEndpointRateLimiter({
      authSecret: settings.secret,
      pool,
      scope: "operator-proof",
    });
    const authEvents = new AuthEventRecorder({
      authSecret: settings.secret,
      backgroundTask: backgroundTasks.handler,
      pool,
    });
    const getSession = (headers: Headers) =>
      auth.api.getSession({
        headers,
        query: { disableCookieCache: true, disableRefresh: true },
      });
    const operatorDirectory = new OperatorDirectoryService({
      authSecret: settings.secret,
      pool,
    });
    const operatorCodes = new OperatorEmailCode({auth, pool, delivery: emailCodes, coordinator: credentialCoordinator});
    const operatorProofs = new OperatorProofService({pool, verifyCode: operatorCodes.verify});
    const researcherAccess = new ResearcherAccessService({
      authSecret: settings.secret,
      credentialCoordinator,
      pool,
    });
    const operatorSessionRevocations = new OperatorSessionRevocationService({
      access: researcherAccess,
      proofs: operatorProofs,
    });
    const billing=new BillingService({pool,settings:readBillingSettings(process.env,settings.environment),publicOrigin:settings.publicOrigin});
    const billingRoutes=createBillingApp({billing,publicOrigin:settings.publicOrigin,requireResearcher:async(request)=>{
      const result=await loadActiveSession({getSession:input=>auth.api.getSession(input)},request.headers);
      if(result.kind!=="active")return Response.json({code:result.kind==="invalid"?"UNAUTHENTICATED":"AUTH_UNAVAILABLE"},{status:result.kind==="invalid"?401:503});
      return {id:result.user.id,email:result.user.email};
    }});
    const app = createAuthApp({
      authHandler: (request) =>
        credentialCoordinator.handleAuthRequest(
          request,
          (coordinated) =>
            authEvents.handle(
              coordinated,
              (delegated) => auth.handler(delegated),
              getSession,
            ),
          getSession,
        ),
      consumeOperatorProofRateLimit: (sessionId, headers) =>
        operatorProofRateLimiter.consume(sessionId, headers),
      getSession: (input) => auth.api.getSession(input),
      isOperator: (researcherId) => operatorDirectory.isOperator(researcherId),
      researcherPlan: (id) => researcherPlan(pool, id),
      hasOperatorCapability: (principal) =>
        operatorDirectory.hasCapability(principal),
      httpObserver: createAuthHttpObserver(),
      turnstileSiteKey: settings.turnstileSiteKey,
      admitSignInCode: (email, token, headers) => signInAdmission.admit(email, token, headers),
      sendSignInCode: email => emailCodes.send(email, "sign-in"),
      consumeEmailCodeRateLimit: (email, headers) => emailCodeRateLimiter.consume(email, headers),
      sendOperatorCode: principal => operatorCodes.send(principal),
      confirmOperatorProof: (principal, input) =>
        operatorProofs.confirm(principal, input),
      consumeOperatorProof: async (principal, input) => {
        await operatorProofs.consumeExternal(principal, input);
      },
      listOperatorResearchers: (principal, input) =>
        operatorDirectory.listResearchers(principal, input),
      issueMcpAccessToken,
      publicOrigin: settings.publicOrigin,
      readiness: () => checkAuthReadiness(pool),
      revokeOperatorResearcherSessions: (principal, input) =>
        operatorSessionRevocations.revoke(principal, input),
    }, createMcpConnectionsApp(auth, pool, settings, coordination),billingRoutes);
    const server = serve({
      fetch: app.fetch,
      hostname: settings.host,
      port: settings.port,
    });
    backgroundTasks.handler(runAuthCleanup(pool));
    const cleanupInterval = setInterval(() => {
      backgroundTasks.handler(runAuthCleanup(pool));
    }, 24 * 60 * 60 * 1_000);
    cleanupInterval.unref();

    let reconciling=false;
    const reconcileBilling=async()=>{if(reconciling)return;reconciling=true;try{await billing.reconcile();}finally{reconciling=false;}};
    backgroundTasks.handler(reconcileBilling());
    const billingInterval=setInterval(()=>backgroundTasks.handler(reconcileBilling()),30_000);
    billingInterval.unref();
    let closing = false;
    const close = () => {
      if (closing) {
        return;
      }
      closing = true;
      clearInterval(cleanupInterval);
      clearInterval(billingInterval);
      server.close(() => {
        void backgroundTasks
          .drain()
          .then(async () => {
            await Promise.allSettled([coordinationPool.end(), pool.end()]);
            process.exitCode = 0;
          });
      });
    };
    process.once("SIGINT", close);
    process.once("SIGTERM", close);
  } catch (error) {
    await Promise.allSettled([coordinationPool.end(), pool.end()]);
    throw error;
  }
}

main().catch((error: unknown) => {
  process.stderr.write(
    `${JSON.stringify({
      code: "AUTH_STARTUP_INVALID",
      event: "auth_startup_failed",
      ...diagnoseAuthFailure(error),
    })}\n`,
  );
  process.exitCode = 1;
});
