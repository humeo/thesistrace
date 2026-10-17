import { parseArgs } from "node:util";
import { Pool } from "pg";
import { BillingService } from "./billing.js";
import { readBillingSettings } from "./billing-config.js";
import { verifyAuthSchema } from "./schema-contract.js";

async function main() {
  const { positionals, values } = parseArgs({
    allowPositionals: true,
    options: { evidence: { type: "string" }, checkout: { type: "string" } },
  });
  const [command, id] = positionals;
  if (
    positionals.length !== 2 ||
    !id ||
    ![
      "replay-event",
      "resolve-dispute",
      "recover-checkout",
      "reject-unapplied",
    ].includes(command!)
  )
    throw new Error(
      "Use replay-event EVENT | resolve-dispute TRANSACTION --evidence REFERENCE | recover-checkout REQUEST --checkout CHECKOUT",
    );
  const connectionString = process.env.THESISTRACE_OWNER_DATABASE_URL;
  if (!connectionString) throw new Error("Owner database connection required");
  const pool = new Pool({ connectionString });
  try {
    if (
      (await pool.query("SELECT current_user")).rows[0]?.current_user !==
      "thesistrace_owner"
    )
      throw new Error("Owner maintenance required");
    await verifyAuthSchema(pool);
    const runtime = process.env.THESISTRACE_ENVIRONMENT;
    if (
      runtime !== "production" &&
      runtime !== "development" &&
      runtime !== "test"
    )
      throw new Error("Explicit runtime required");
    const billing = new BillingService({
      pool,
      settings: readBillingSettings(process.env, runtime),
      publicOrigin: "https://maintenance.invalid",
    });
    if (command === "replay-event") await billing.replayEvent(id);
    if (command === "resolve-dispute")
      await billing.resolveDispute(id, values.evidence ?? "");
    if (command === "reject-unapplied")
      await billing.rejectUnappliedCommand(id, values.evidence ?? "");
    if (command === "recover-checkout")
      await billing.recoverCheckout(id, values.checkout ?? "");
    process.stdout.write(
      JSON.stringify({ command, id, status: "completed" }) + "\n",
    );
  } finally {
    await pool.end();
  }
}
main().catch(() => {
  process.stderr.write(
    JSON.stringify({ code: "BILLING_MAINTENANCE_FAILED" }) + "\n",
  );
  process.exitCode = 1;
});
