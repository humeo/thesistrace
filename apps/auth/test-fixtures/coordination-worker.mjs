import {
  AuthOperationCoordinator,
} from "../dist/coordination.js";
import { createAuthCoordinationPool } from "../dist/database.js";

const databaseUrl = process.env.THESISTRACE_AUTH_DATABASE_URL;
if (databaseUrl === undefined) {
  throw new Error("THESISTRACE_AUTH_DATABASE_URL is required");
}

const pool = createAuthCoordinationPool(databaseUrl);
pool.on("error", () => undefined);
const originalConnect = pool.connect.bind(pool);
pool.connect = async () => {
  const client = await originalConnect();
  client.once("error", () => {
    process.send?.({ event: "coordination_connection_failed" });
  });
  return client;
};
const coordinator = new AuthOperationCoordinator(pool);
let releaseOperation = () => undefined;
const operationGate = new Promise((resolve) => {
  releaseOperation = resolve;
});
let coordinatorSettled = false;
const handleMessage = (message) => {
  if (message === null || typeof message !== "object" || !("command" in message)) {
    return;
  }
  if (message.command === "release") {
    process.off("message", handleMessage);
    releaseOperation();
  } else if (message.command === "status") {
    process.send?.({ event: "coordination_status", settled: coordinatorSettled });
  }
};
process.on("message", handleMessage);

try {
  const coordinating = coordinator.run(
    ["coordination-process-regression"],
    async () => {
    process.send?.({ event: "coordination_started" });
      await operationGate;
    },
  );
  void coordinating.then(
    () => {
      coordinatorSettled = true;
    },
    () => {
      coordinatorSettled = true;
    },
  );
  await coordinating;
  process.stdout.write('{"status":"completed"}\n');
} catch {
  process.stderr.write(
    '{"code":"AUTH_COORDINATION_UNAVAILABLE","event":"coordination_failed"}\n',
  );
  process.exitCode = 1;
} finally {
  await pool.end();
  if (process.connected) {
    process.disconnect();
  }
}
