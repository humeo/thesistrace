import { ResearcherAccessService } from "./access.js";
import { createThesisTraceAuth } from "./auth.js";
import { AuthBackgroundTasks } from "./background-tasks.js";
import { readAuthSettings } from "./config.js";
import {
  AuthOperationCoordinator,
  CredentialOperationCoordinator,
} from "./coordination.js";
import { createAuthCoordinationPool, createAuthPool } from "./database.js";
import { diagnoseAuthFailure } from "./failure.js";
import { ResearcherInvitationService } from "./invitation.js";
import { InvitationAdmission } from "./invitation-admission.js";
import { OperatorAssignmentService } from "./operator-assignment.js";
import { runOperatorCommand } from "./operator-command.js";
import { PasswordResetLifecycle } from "./password-reset.js";
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
    const backgroundTasks = new AuthBackgroundTasks();
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
    const result = await runOperatorCommand(process.argv.slice(2), {
      access: new ResearcherAccessService({
        authSecret: settings.secret,
        pool,
      }),
      assignment: new OperatorAssignmentService({ pool }),
      invitations: new ResearcherInvitationService({
        auth,
        authSecret: settings.secret,
        credentialCoordinator,
        invitationAdmission,
        pool,
        publicOrigin: settings.publicOrigin,
        sendEmail,
      }),
    });
    process.stdout.write(`${JSON.stringify(result)}\n`);
    process.stderr.write(
      `${JSON.stringify({
        command: result.command,
        event: "auth_operator_completed",
        status: result.status,
      })}\n`,
    );
    await backgroundTasks.drain();
  } finally {
    await Promise.allSettled([coordinationPool.end(), pool.end()]);
  }
}

main().catch((error: unknown) => {
  process.stderr.write(
    `${JSON.stringify({
      code: safeErrorCode(error),
      event: "auth_operator_failed",
    })}\n`,
  );
  process.exitCode = 1;
});

function safeErrorCode(error: unknown): string {
  if (
    error !== null &&
    typeof error === "object" &&
    "code" in error &&
    typeof error.code === "string" &&
    /^[A-Z][A-Z0-9_]{2,63}$/.test(error.code)
  ) {
    return error.code;
  }
  return "AUTH_OPERATOR_FAILED";
}
