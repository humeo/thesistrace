import { serve } from "@hono/node-server";

import { createAuthApp } from "./app.js";
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
import { ResearcherInvitationService } from "./invitation.js";
import { InvitationAdmission } from "./invitation-admission.js";
import { createMcpAccessTokenIssuer } from "./mcp-access-token.js";
import { PasswordResetLifecycle } from "./password-reset.js";
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
    const invitationAdmission = new InvitationAdmission();
    const sendEmail = (email: Parameters<typeof sendResendEmail>[1]) =>
      sendResendEmail(
        {
          apiKey: settings.resendApiKey,
          apiUrl: settings.resendApiUrl,
          fromEmail: settings.resendFromEmail,
        },
        email,
      );
    const passwordReset = new PasswordResetLifecycle({
      authSecret: settings.secret,
      backgroundTask: backgroundTasks.handler,
      credentialCoordinator,
      pool,
      publicOrigin: settings.publicOrigin,
      sendEmail,
    });
    const auth = createThesisTraceAuth(settings, pool, {
      backgroundTask: backgroundTasks.handler,
      invitationAdmission,
      isResearcherActive: passwordReset.isResearcherActive,
      sendResetPassword: passwordReset.sendResetPassword,
    });
    const issueMcpAccessToken = createMcpAccessTokenIssuer(settings, {
      sign: (payload) => auth.api.signJWT({ body: { payload } }),
    });
    const invitations = new ResearcherInvitationService({
      auth,
      authSecret: settings.secret,
      credentialCoordinator,
      invitationAdmission,
      pool,
      publicOrigin: settings.publicOrigin,
      sendEmail,
    });
    const invitationRateLimiter = new AuthEndpointRateLimiter({
      authSecret: settings.secret,
      pool,
      scope: "researcher-invitation",
    });
    const passwordResetRateLimiter = new AuthEndpointRateLimiter({
      authSecret: settings.secret,
      pool,
      scope: "password-reset",
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
    const app = createAuthApp({
      acceptInvitation: (token, password, headers) =>
        invitations.accept(token, password, headers),
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
      consumeInvitationRateLimit: (token, headers) =>
        invitationRateLimiter.consume(token, headers),
      consumePasswordResetRateLimit: (token, headers) =>
        passwordResetRateLimiter.consume(token, headers),
      getSession: (input) => auth.api.getSession(input),
      httpObserver: createAuthHttpObserver(),
      inspectInvitation: (token) => invitations.inspect(token),
      issueMcpAccessToken,
      publicOrigin: settings.publicOrigin,
      readiness: () => checkAuthReadiness(pool),
      resetPassword: passwordReset.completeReset,
    });
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

    let closing = false;
    const close = () => {
      if (closing) {
        return;
      }
      closing = true;
      clearInterval(cleanupInterval);
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
