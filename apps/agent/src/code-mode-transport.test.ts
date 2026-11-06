import { IsolatedVmCodeModeTransport } from "@mastra/isolated-vm";
import { createRequire } from "node:module";
import { describe, expect, it } from "vitest";

describe("Code Mode execution isolation", () => {
  it.each(["esm", "commonjs"])("returns computed data without retaining console content on the Host: %s", async mode => {
    const Transport = mode === "esm" ? IsolatedVmCodeModeTransport : createRequire(import.meta.url)("@mastra/isolated-vm").IsolatedVmCodeModeTransport as typeof IsolatedVmCodeModeTransport;
    const transport = new Transport({ memoryLimitMb: 64 });
    const result = await transport.run({
      program: 'console.log("private-result-canary"); return { total: 7 * 6 };',
      toolIds: [], dispatch: async () => undefined, timeout: 2_000,
    });
    expect(result).toEqual({ success: true, result: { total: 42 }, logs: [] });
  });

  it.each([
    ['return "x".repeat(256 * 1024 + 1);', []],
    ['return external_read({ value: "x".repeat(64 * 1024 + 1) });', ["read"]],
  ])("rejects oversized data before crossing the isolate seam", async (program, toolIds) => {
    const result = await new IsolatedVmCodeModeTransport({ memoryLimitMb: 64 }).run({
      program, toolIds, dispatch: async () => 42, timeout: 2_000,
    });
    expect(result).toMatchObject({ success: false, error: { name: "CodeModeLimitError" } });
    expect(JSON.stringify(result).length).toBeLessThan(1_024);
  });

  it("keeps file, network, process and module capabilities outside the program", async () => {
    const result = await new IsolatedVmCodeModeTransport().run({
      program: 'return [typeof process, typeof require, typeof fetch, typeof Buffer];',
      toolIds: [], dispatch: async () => undefined, timeout: 2_000,
    });
    expect(result).toMatchObject({ success: true, result: ["undefined", "undefined", "undefined", "undefined"] });
  });

  it("stops a synchronous loop while the Host remains responsive", async () => {
    const controller = new AbortController();
    let hostResponded = false;
    const result = await new IsolatedVmCodeModeTransport().run({
      program: 'await external_started({}); while (true) {}', toolIds: ["started"], timeout: 2_000,
      abortSignal: controller.signal,
      dispatch: async () => {
        setTimeout(() => { hostResponded = true; controller.abort(); }, 10);
        return null;
      },
    });
    expect(hostResponded).toBe(true);
    expect(result).toMatchObject({ success: false, error: { name: "AbortError" } });
  });

  it("bounds synchronous and asynchronous hangs and releases the isolate", async () => {
    const transport = new IsolatedVmCodeModeTransport();
    for (const program of ['while (true) {}', 'await new Promise(() => {});']) {
      const result = await transport.run({ program, toolIds: [], dispatch: async () => undefined, timeout: 20 });
      expect(result).toMatchObject({ success: false, error: { name: "TimeoutError" } });
    }
    await expect(transport.run({ program: "return 42;", toolIds: [], dispatch: async () => undefined, timeout: 2_000 }))
      .resolves.toMatchObject({ success: true, result: 42 });
  });

  it("contains heap exhaustion and remains usable for the next program", async () => {
    const transport = new IsolatedVmCodeModeTransport({ memoryLimitMb: 16 });
    const result = await transport.run({ program: "const rows = []; while (true) rows.push(new Array(10000).fill(42));",
      toolIds: [], dispatch: async () => undefined, timeout: 2_000 });
    expect(result).toMatchObject({ success: false, error: { name: "CodeModeLimitError" } });
    await expect(transport.run({ program: "return 42;", toolIds: [], dispatch: async () => undefined, timeout: 2_000 }))
      .resolves.toMatchObject({ success: true, result: 42 });
  });

  it("counts UTF-8 and keeps cross-isolate budgets independent of guest global mutations", async () => {
    const transport = new IsolatedVmCodeModeTransport();
    await expect(transport.run({ program: 'return await external_read({value: "😀".repeat(16000)});',
      toolIds: ["read"], dispatch: async () => 42, timeout: 2_000 })).resolves.toMatchObject({ success: true, result: 42 });
    await expect(transport.run({ program: 'JSON.stringify = () => ""; String.prototype.charCodeAt = () => 0; return "😀".repeat(70000);',
      toolIds: [], dispatch: async () => null, timeout: 2_000 })).resolves.toMatchObject({ success: false, error: { name: "CodeModeLimitError" } });
  });

  it.each([
    'try { await external_read({value:"x".repeat(70000)}); } catch {} return 42;',
    'Object.defineProperty(Error.prototype,"name",{get(){return "TypeError"},set(){}}); try { await external_read({value:"x".repeat(70000)}); } catch {} return 42;',
  ])("records argument exhaustion outside guest exception handling", async program => {
    let calls = 0;
    const result = await new IsolatedVmCodeModeTransport().run({ program, toolIds: ["read"], dispatch: async () => { calls++; return 1; }, timeout: 2_000 });
    expect(result).toMatchObject({ success: false, error: { name: "CodeModeLimitError" } });
    expect(calls).toBe(0);
  });
});
