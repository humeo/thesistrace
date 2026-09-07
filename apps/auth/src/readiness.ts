import type { Pool } from "pg";

import { verifyAuthSchema } from "./schema-contract.js";

export async function checkAuthReadiness(database: Pool): Promise<boolean> {
  try {
    await verifyAuthSchema(database);
    await database.query('SELECT 1 FROM auth."session" LIMIT 1');
    return true;
  } catch {
    return false;
  }
}
