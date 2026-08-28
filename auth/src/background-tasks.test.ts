import { describe, expect, it, vi } from "vitest";

import { AuthBackgroundTasks } from "./background-tasks.js";

describe("Auth background task ownership", () => {
  it("drains accepted work and sanitizes a rejected task through one callback", async () => {
    const onError = vi.fn();
    const tasks = new AuthBackgroundTasks(onError);
    let complete: (() => void) | undefined;
    const pending = new Promise<void>((resolve) => {
      complete = resolve;
    });

    tasks.handler(pending);
    tasks.handler(Promise.reject(new Error("token-canary private-provider-body")));
    complete?.();
    await expect(tasks.drain()).resolves.toBeUndefined();

    expect(onError).toHaveBeenCalledOnce();
    expect(onError).toHaveBeenCalledWith(expect.any(Error));
  });
});
