import { describe, expect, it, vi } from "vitest";

import {
  createAgentInitializerPool,
  createAgentPool,
  createAgentReadinessPool,
} from "./database.js";

describe("Agent database pools", () => {
  it("handles idle-client failures without crashing or logging error content", async () => {
    const pools = [
      createAgentPool("postgresql://agent.invalid/agent"),
      createAgentReadinessPool("postgresql://agent.invalid/agent"),
      createAgentInitializerPool("postgresql://agent.invalid/agent"),
    ];
    const writes: string[] = [];
    const write = vi.spyOn(process.stderr, "write").mockImplementation((chunk) => {
      writes.push(String(chunk));
      return true;
    });
    try {
      for (const pool of pools) {
        expect(pool.listenerCount("error")).toBe(1);
      }

      const error = Object.assign(new Error("private database detail"), {
        code: "57P01",
      });
      expect(() => pools[0]?.emit("error", error)).not.toThrow();

      expect(writes).toEqual([
        `${JSON.stringify({
          code: "AGENT_DATABASE_UNAVAILABLE",
          event: "agent_database_pool_error",
          reason: "DATABASE_UNAVAILABLE",
          sqlstate: "57P01",
        })}\n`,
      ]);
      expect(writes.join("\n")).not.toContain("private database detail");
    } finally {
      write.mockRestore();
      await Promise.all(pools.map(async (pool) => pool.end()));
    }
  });
});
