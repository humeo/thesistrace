import { spawnSync } from "node:child_process";
import {
  chmodSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, it } from "vitest";

const runner = fileURLToPath(new URL("../../../tooling/test/app.mjs", import.meta.url));
const temporaryDirectories: string[] = [];

afterEach(() => {
  for (const directory of temporaryDirectories.splice(0)) {
    rmSync(directory, { force: true, recursive: true });
  }
});

describe("Auth test runner process contract", () => {
  it.each([
    ["int", 130],
    ["term", 143],
  ])("preserves the %s signal status through cleanup", (signal, status) => {
    const fixture = createFixture();

    const completed = spawnSync(runner, ["auth", "runner-contract-self-check", signal], {
      encoding: "utf8",
      env: {
        ...process.env,
        FAKE_DOCKER_DOWN_STATUS: "0",
        FAKE_DOCKER_LOG: fixture.log,
        PATH: `${fixture.directory}:${process.env.PATH ?? ""}`,
        TMPDIR: fixture.directory,
      },
      killSignal: "SIGKILL",
      timeout: 5_000,
    });

    expect(completed.error).toBeUndefined();
    expect(completed.signal).toBeNull();
    expect(completed.status).toBe(status);
    expect(readFixtureLog(fixture.log)).toContain("down --volumes --remove-orphans");
  });

  it("turns a cleanup failure into a failed test run", () => {
    const fixture = createFixture();

    const completed = spawnSync(
      runner,
      ["auth", "runner-contract-self-check", "success"],
      {
        encoding: "utf8",
        env: {
          ...process.env,
          FAKE_DOCKER_DOWN_STATUS: "42",
          FAKE_DOCKER_LOG: fixture.log,
          PATH: `${fixture.directory}:${process.env.PATH ?? ""}`,
          TMPDIR: fixture.directory,
        },
        killSignal: "SIGKILL",
        timeout: 5_000,
      },
    );

    expect(completed.error).toBeUndefined();
    expect(completed.status).toBe(42);
    expect(completed.stderr).toContain("Auth test cleanup failed");
    expect(completed.stderr).toContain("Auth test evidence:");
  });

  it("does not let ambient state bypass a formal integration run", () => {
    const fixture = createFixture();

    const completed = spawnSync(runner, ["auth", "integration"], {
      encoding: "utf8",
      env: {
        ...process.env,
        FAKE_DOCKER_CONFIG_STATUS: "37",
        FAKE_DOCKER_DOWN_STATUS: "0",
        FAKE_DOCKER_LOG: fixture.log,
        PATH: `${fixture.directory}:${process.env.PATH ?? ""}`,
        THESISTRACE_AUTH_TEST_RUNNER_SELF_CHECK: "success",
        TMPDIR: fixture.directory,
      },
      killSignal: "SIGKILL",
      timeout: 5_000,
    });

    expect(completed.error).toBeUndefined();
    expect(completed.status).toBe(37);
    expect(readFixtureLog(fixture.log)).toContain("config --quiet");
  });
});

function createFixture(): Readonly<{
  directory: string;
  log: string;
}> {
  const directory = mkdtempSync(join(tmpdir(), "thesistrace-auth-runner."));
  temporaryDirectories.push(directory);
  const log = join(directory, "docker.log");
  const docker = join(directory, "docker");
  writeFileSync(
    docker,
    `#!/bin/sh
set -eu
printf '%s\\n' "$*" >>"$FAKE_DOCKER_LOG"
case " $* " in
  *" down --volumes --remove-orphans "*) exit "$FAKE_DOCKER_DOWN_STATUS" ;;
  *" config --quiet "*) exit "\${FAKE_DOCKER_CONFIG_STATUS:-0}" ;;
esac
exit 0
`,
  );
  chmodSync(docker, 0o755);
  return { directory, log };
}

function readFixtureLog(path: string): string {
  return readFileSync(path, "utf8");
}
