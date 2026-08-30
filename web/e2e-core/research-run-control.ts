import { execFileSync, spawn, type ChildProcess } from "node:child_process";

import { testProjectName } from "./auth-fixture";

export function controlWorker(
  action: "pause" | "unpause",
  service: "research-worker" | "batch-research-worker" | "tracking-worker" = "research-worker",
): void {
  execFileSync("docker", [action, `${testProjectName()}-${service}-1`], {
    stdio: "pipe",
    timeout: 10_000,
  });
}

export function startControlledResearchRun(runId: string) {
  testProjectName();
  const worker = spawn(
    "uv",
    ["run", "python", "../tests/browser/process_research_run_with_barrier.py", runId],
    { cwd: process.cwd(), env: process.env, stdio: "pipe" },
  );
  const claimed = new Promise<void>((resolve, reject) => {
    let stdout = "";
    let stderr = "";
    const deadline = setTimeout(() => {
      reject(new Error(`Controlled ResearchRun was not claimed: ${stdout}\n${stderr}`));
    }, 30_000);
    worker.stdout.setEncoding("utf8");
    worker.stderr.setEncoding("utf8");
    worker.stderr.on("data", (chunk: string) => { stderr += chunk; });
    worker.stdout.on("data", (chunk: string) => {
      stdout += chunk;
      if (stdout.includes(`claimed:${runId}`)) {
        clearTimeout(deadline);
        resolve();
      }
    });
    worker.once("error", (error) => {
      clearTimeout(deadline);
      reject(error);
    });
    worker.once("exit", (code) => {
      clearTimeout(deadline);
      if (!stdout.includes(`claimed:${runId}`)) {
        reject(new Error(`Controlled ResearchRun worker exited ${code}: ${stderr}`));
      }
    });
  });
  return { claimed, process: worker };
}

export function controlledWorkerExit(
  worker: ChildProcess,
  allowTermination = false,
): Promise<void> {
  const successful = (code: number | null, signal: NodeJS.Signals | null) => (
    code === 0 || (allowTermination && (signal === "SIGTERM" || code === 143))
  );
  if (worker.exitCode !== null || worker.signalCode !== null) {
    return successful(worker.exitCode, worker.signalCode)
      ? Promise.resolve()
      : Promise.reject(new Error(
        `Controlled ResearchRun worker exited with ${worker.exitCode ?? worker.signalCode}`,
      ));
  }
  return new Promise((resolve, reject) => {
    const deadline = setTimeout(() => {
      reject(new Error("Controlled ResearchRun worker did not exit within 90 seconds"));
    }, 90_000);
    worker.once("error", (error) => {
      clearTimeout(deadline);
      reject(error);
    });
    worker.once("exit", (code, signal) => {
      clearTimeout(deadline);
      if (successful(code, signal)) resolve();
      else reject(new Error(`Controlled ResearchRun worker exited with ${code ?? signal}`));
    });
  });
}
