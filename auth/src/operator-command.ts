import type {
  AccessMutationResult,
  ResearcherAccessService,
} from "./access.js";
import type {
  InvitationIssueResult,
  ResearcherInvitationService,
} from "./invitation.js";
import type {
  OperatorAssignmentService,
  OperatorIdentity,
} from "./operator-assignment.js";

type AccessCommand =
  | "correct-label"
  | "deactivate"
  | "reactivate"
  | "revoke-sessions";

const accessCommands: ReadonlySet<AccessCommand> = new Set([
  "correct-label",
  "deactivate",
  "reactivate",
  "revoke-sessions",
]);

export class OperatorArgumentError extends Error {
  readonly code = "AUTH_OPERATOR_ARGUMENT_INVALID";

  constructor() {
    super("AUTH_OPERATOR_ARGUMENT_INVALID");
    this.name = "OperatorArgumentError";
  }
}

type AccessOperations = Pick<
  ResearcherAccessService,
  | "correctDisplayLabel"
  | "deactivate"
  | "reactivate"
  | "resolveResearcherId"
  | "revokeSessions"
>;

type InvitationOperations = Pick<
  ResearcherInvitationService,
  "issue" | "reissue"
>;

type AssignmentOperations = Pick<
  OperatorAssignmentService,
  "assign" | "transfer"
>;

export type OperatorCommandDependencies = Readonly<{
  access: AccessOperations;
  assignment: AssignmentOperations;
  invitations: InvitationOperations;
}>;

export type OperatorCommandResult =
  | Readonly<{
      command: "resolve";
      researcher_id: string;
      status: "resolved";
    }>
  | Readonly<{
      command: "assign-operator";
      researcher_id: string;
      status: "assigned";
    }>
  | Readonly<{
      command: "transfer-operator";
      former_researcher_id: string;
      researcher_id: string;
      status: "no_change" | "transferred";
    }>
  | Readonly<{
      command: "invite" | "reissue";
      email: string;
      invitation_id: string;
      status: "delivered";
    }>
  | Readonly<{
      command:
        | "correct-label"
        | "deactivate"
        | "reactivate"
        | "revoke-sessions";
      researcher_id: string;
      status: AccessMutationResult["status"];
    }>;

export async function runOperatorCommand(
  args: readonly string[],
  dependencies: OperatorCommandDependencies,
): Promise<OperatorCommandResult> {
  const command = args[0];
  if (command === "assign-operator" || command === "transfer-operator") {
    const flags = parseFlags(
      args.slice(1),
      new Set(["--email", "--researcher-id"]),
    );
    if (flags.size !== 1) {
      throw new OperatorArgumentError();
    }
    const identity = parseIdentity(flags);
    if (command === "assign-operator") {
      const result = await dependencies.assignment.assign(identity);
      return {
        command,
        researcher_id: result.operatorResearcherId,
        status: result.status,
      };
    }
    const result = await dependencies.assignment.transfer(identity);
    return {
      command,
      former_researcher_id: result.formerOperatorResearcherId,
      researcher_id: result.operatorResearcherId,
      status: result.status,
    };
  }
  if (command === "invite" || command === "reissue") {
    const flags = parseFlags(args.slice(1), new Set(["--email"]));
    if (flags.size !== 1 || !flags.has("--email")) {
      throw new OperatorArgumentError();
    }
    const email = requiredFlag(flags, "--email");
    const result = await (command === "invite"
      ? dependencies.invitations.issue(email)
      : dependencies.invitations.reissue(email));
    return invitationResult(command, result);
  }

  if (command === "resolve") {
    const flags = parseFlags(
      args.slice(1),
      new Set(["--email", "--researcher-id"]),
    );
    if (flags.size !== 1) {
      throw new OperatorArgumentError();
    }
    const researcherId = await dependencies.access.resolveResearcherId(
      parseIdentity(flags),
    );
    return {
      command,
      researcher_id: researcherId,
      status: "resolved",
    };
  }

  if (!isAccessCommand(command)) {
    throw new OperatorArgumentError();
  }
  const allowedFlags =
    command === "correct-label"
      ? new Set(["--email", "--label", "--researcher-id"])
      : new Set(["--email", "--researcher-id"]);
  const flags = parseFlags(args.slice(1), allowedFlags);
  const identity = parseIdentity(flags);
  const researcherId = await dependencies.access.resolveResearcherId(identity);

  let result: AccessMutationResult;
  if (command === "correct-label") {
    if (flags.size !== 2 || !flags.has("--label")) {
      throw new OperatorArgumentError();
    }
    result = await dependencies.access.correctDisplayLabel(
      researcherId,
      requiredFlag(flags, "--label"),
    );
  } else {
    if (flags.size !== 1) {
      throw new OperatorArgumentError();
    }
    result = await runAccessMutation(command, researcherId, dependencies.access);
  }
  return {
    command,
    researcher_id: result.researcherId,
    status: result.status,
  };
}

function parseFlags(
  args: readonly string[],
  allowed: ReadonlySet<string>,
): Map<string, string> {
  if (args.length % 2 !== 0) {
    throw new OperatorArgumentError();
  }
  const flags = new Map<string, string>();
  for (let index = 0; index < args.length; index += 2) {
    const name = args[index];
    const value = args[index + 1];
    if (
      name === undefined ||
      value === undefined ||
      !allowed.has(name) ||
      flags.has(name) ||
      value.length === 0 ||
      value.startsWith("--")
    ) {
      throw new OperatorArgumentError();
    }
    flags.set(name, value);
  }
  return flags;
}

function parseIdentity(
  flags: ReadonlyMap<string, string>,
): OperatorIdentity {
  const email = flags.get("--email");
  const researcherId = flags.get("--researcher-id");
  if ((email === undefined) === (researcherId === undefined)) {
    throw new OperatorArgumentError();
  }
  return email === undefined ? { researcherId: researcherId ?? "" } : { email };
}

function requiredFlag(flags: ReadonlyMap<string, string>, name: string): string {
  const value = flags.get(name);
  if (value === undefined) {
    throw new OperatorArgumentError();
  }
  return value;
}

function invitationResult(
  command: "invite" | "reissue",
  result: InvitationIssueResult,
): OperatorCommandResult {
  return {
    command,
    email: result.email,
    invitation_id: result.invitationId,
    status: result.status,
  };
}

function runAccessMutation(
  command: "deactivate" | "reactivate" | "revoke-sessions",
  researcherId: string,
  access: AccessOperations,
): Promise<AccessMutationResult> {
  if (command === "deactivate") {
    return access.deactivate(researcherId);
  }
  if (command === "reactivate") {
    return access.reactivate(researcherId);
  }
  return access.revokeSessions(researcherId);
}

function isAccessCommand(value: string | undefined): value is AccessCommand {
  return value !== undefined && accessCommands.has(value as AccessCommand);
}
