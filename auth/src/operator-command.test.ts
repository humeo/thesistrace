import { describe, expect, it, vi } from "vitest";

import {
  OperatorArgumentError,
  runOperatorCommand,
  type OperatorCommandDependencies,
} from "./operator-command.js";

const researcherId = "00000000-0000-4000-8000-000000000001";

function dependencies(): OperatorCommandDependencies {
  return {
    access: {
      correctDisplayLabel: vi.fn(async () => ({
        researcherId,
        status: "updated" as const,
      })),
      deactivate: vi.fn(async () => ({ researcherId, status: "updated" as const })),
      reactivate: vi.fn(async () => ({ researcherId, status: "updated" as const })),
      resolveResearcherId: vi.fn(async () => researcherId),
      revokeSessions: vi.fn(async () => ({
        researcherId,
        status: "updated" as const,
      })),
    },
    invitations: {
      issue: vi.fn(async () => ({
        email: "researcher@example.com",
        invitationId: "00000000-0000-4000-8000-000000000002",
        status: "delivered" as const,
      })),
      reissue: vi.fn(async () => ({
        email: "researcher@example.com",
        invitationId: "00000000-0000-4000-8000-000000000003",
        status: "delivered" as const,
      })),
    },
  };
}

describe("Auth operator command contract", () => {
  it("resolves an email without mutating Auth state", async () => {
    const commandDependencies = dependencies();

    const result = await runOperatorCommand(
      ["resolve", "--email", " Researcher@Example.COM "],
      commandDependencies,
    );

    expect(commandDependencies.access.resolveResearcherId).toHaveBeenCalledWith({
      email: " Researcher@Example.COM ",
    });
    expect(commandDependencies.access.deactivate).not.toHaveBeenCalled();
    expect(commandDependencies.access.reactivate).not.toHaveBeenCalled();
    expect(commandDependencies.access.revokeSessions).not.toHaveBeenCalled();
    expect(result).toEqual({
      command: "resolve",
      researcher_id: researcherId,
      status: "resolved",
    });
  });

  it.each(["invite", "reissue"])(
    "returns a token-free structured %s result",
    async (command) => {
      const result = await runOperatorCommand(
        [command, "--email", "researcher@example.com"],
        dependencies(),
      );
      const output = `${JSON.stringify(result)}\n`;

      expect(result).toMatchObject({
        command,
        email: "researcher@example.com",
        status: "delivered",
      });
      expect(output.trim().split("\n")).toHaveLength(1);
      expect(output).not.toContain("#token=");
      expect(output).not.toContain("accept-invitation");
    },
  );

  it.each(["deactivate", "reactivate", "revoke-sessions"])(
    "resolves an explicit email then runs %s",
    async (command) => {
      const commandDependencies = dependencies();
      const result = await runOperatorCommand(
        [command, "--email", " Researcher@Example.COM "],
        commandDependencies,
      );

      expect(commandDependencies.access.resolveResearcherId).toHaveBeenCalledWith({
        email: " Researcher@Example.COM ",
      });
      expect(result).toEqual({ command, researcher_id: researcherId, status: "updated" });
    },
  );

  it("corrects a label using an explicit Researcher ID", async () => {
    const commandDependencies = dependencies();
    const result = await runOperatorCommand(
      [
        "correct-label",
        "--researcher-id",
        researcherId,
        "--label",
        "Research Lead",
      ],
      commandDependencies,
    );

    expect(commandDependencies.access.correctDisplayLabel).toHaveBeenCalledWith(
      researcherId,
      "Research Lead",
    );
    expect(result).toEqual({
      command: "correct-label",
      researcher_id: researcherId,
      status: "updated",
    });
  });

  it.each([
    { args: [] },
    { args: ["unknown"] },
    { args: ["invite", "--researcher-id", researcherId] },
    {
      args: [
        "deactivate",
        "--email",
        "a@example.com",
        "--researcher-id",
        researcherId,
      ],
    },
    { args: ["correct-label", "--researcher-id", researcherId] },
    { args: ["reactivate", "--email"] },
    { args: ["revoke-sessions", "--unexpected", "secret-canary"] },
  ])("rejects malformed arguments without reflecting their value: $args", async ({ args }) => {
    await expect(runOperatorCommand(args, dependencies())).rejects.toEqual(
      new OperatorArgumentError(),
    );
  });
});
