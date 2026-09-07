import { createServer, type Socket } from "node:net";

import { afterEach, describe, expect, it } from "vitest";

import { createAuthPool } from "./database.js";
import { diagnoseAuthFailure } from "./failure.js";

describe("Auth PostgreSQL connection budget", () => {
  const sockets = new Set<Socket>();

  afterEach(() => {
    for (const socket of sockets) {
      socket.destroy();
    }
    sockets.clear();
  });

  it("terminates a PostgreSQL handshake that accepts TCP but never responds", async () => {
    const server = createServer((socket) => {
      sockets.add(socket);
      socket.on("close", () => sockets.delete(socket));
    });
    await new Promise<void>((resolve, reject) => {
      server.once("error", reject);
      server.listen(0, "127.0.0.1", resolve);
    });
    const address = server.address();
    if (address === null || typeof address === "string") {
      throw new Error("expected a TCP test address");
    }
    const pool = createAuthPool(
      `postgresql://auth_runtime:password@127.0.0.1:${address.port}/thesistrace`,
    );
    const startedAt = performance.now();
    try {
      let failure: unknown;
      try {
        await pool.query("SELECT 1");
      } catch (error) {
        failure = error;
      }
      expect(failure).toBeInstanceOf(Error);
      expect(diagnoseAuthFailure(failure)).toEqual({
        reason: "DATABASE_UNAVAILABLE",
      });
      expect(performance.now() - startedAt).toBeLessThan(4_000);
    } finally {
      await pool.end();
      for (const socket of sockets) {
        socket.destroy();
      }
      await new Promise<void>((resolve, reject) => {
        server.close((error) => (error === undefined ? resolve() : reject(error)));
      });
    }
  });
});
