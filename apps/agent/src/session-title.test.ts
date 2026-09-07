import { afterEach, describe, expect, it, vi } from "vitest";

import { ScriptedLanguageModel } from "./scripted-language-model.js";
import {
  SessionTitleGenerator,
  generateSessionTitle,
  parseGeneratedSessionTitle,
} from "./session-title.js";
import { UNTITLED_SESSION_TITLE } from "./session-management.js";

afterEach(() => {
  vi.useRealTimers();
});

describe("Session title generation", () => {
  it("uses one no-Tool Scripted model operation and returns compact plain text", async () => {
    const title = await generateSessionTitle({
      languageModel: new ScriptedLanguageModel("scripted-v1"),
      message: "Build a low-volatility quality Alpha for CSI1000.",
      providerOptions: {},
      timeoutMs: 500,
    });

    expect(title).not.toBe(UNTITLED_SESSION_TITLE);
    expect([...title].length).toBeLessThanOrEqual(80);
    expect(parseGeneratedSessionTitle(title)).toBe(title);
  });

  it.each([
    "",
    "Untitled",
    "\"Untitled\"",
    "Title: Untitled",
    "Title—Quality Alpha",
    "标题：低波动 Alpha",
    "标题—低波动 Alpha",
    "「盈利稳定研究」",
    "《盈利稳定研究》",
    "**Quality Alpha**",
    "Quality **Alpha** research",
    "[Quality Alpha](https://example.invalid)",
    "[Quality Alpha][research]",
    "_Quality Alpha_",
    "Low-volatility _quality_ Alpha",
    "Quality ~~Alpha~~ research",
    "1. Quality Alpha",
    "2) Earnings stability",
    "1234. Quality Alpha",
    "<!-- Quality Alpha -->",
    "«Quality Alpha»",
    "Quality 'Alpha' research",
    "<strong>Quality Alpha</strong>",
    "# Research title",
    "\\# Research title",
    "＂Quality Alpha＂",
    "Research\nTitle",
    "`Research title`",
    "\uFE0F",
    "\u0301Alpha",
    "a".repeat(81),
  ])("rejects unsafe or non-compact generated output: %s", (value) => {
    expect(() => parseGeneratedSessionTitle(value)).toThrow();
  });

  it("aborts a title model that exceeds the deterministic deadline", async () => {
    vi.useFakeTimers();
    const model = new ScriptedLanguageModel("scripted-v1");
    let observedAbort = false;
    vi.spyOn(model, "doGenerate").mockImplementation(async (options) => (
      new Promise((_, reject) => {
        const signal = options.abortSignal;
        const abort = () => {
          observedAbort = true;
          reject(signal?.reason ?? new Error("TITLE_ABORTED"));
        };
        if (signal?.aborted === true) abort();
        else signal?.addEventListener("abort", abort, { once: true });
      })
    ));

    const title = generateSessionTitle({
      languageModel: model,
      message: "Build a quality Alpha.",
      providerOptions: {},
      timeoutMs: 50,
    });
    const rejected = expect(title).rejects.toThrow();
    await vi.advanceTimersByTimeAsync(50);

    await rejected;
    expect(observedAbort).toBe(true);
  });

  it("deduplicates an in-flight title, persists once, and retries after failure", async () => {
    let resolveFirst: (title: string) => void = () => undefined;
    const first = new Promise<string>((resolve) => {
      resolveFirst = resolve;
    });
    const generate = vi.fn()
      .mockImplementationOnce(async () => first)
      .mockRejectedValueOnce(new Error("private provider detail"));
    const storeGeneratedTitle = vi.fn(async () => true);
    const generator = new SessionTitleGenerator(
      { storeGeneratedTitle },
      generate,
    );
    const request = {
      languageModel: new ScriptedLanguageModel("scripted-v1"),
      message: "Research an Alpha.",
      providerOptions: {},
      researcherId: "00000000-0000-4000-8000-000000000001",
      threadId: "00000000-0000-4000-8000-000000000111",
    };

    generator.schedule(request);
    generator.schedule(request);
    resolveFirst("Quality Alpha");
    await generator.settled();

    expect(generate).toHaveBeenCalledOnce();
    expect(storeGeneratedTitle).toHaveBeenCalledWith(
      request.threadId,
      request.researcherId,
      "Quality Alpha",
    );

    generator.schedule(request);
    await expect(generator.settled()).resolves.toBeUndefined();
    expect(generate).toHaveBeenCalledTimes(2);
    expect(storeGeneratedTitle).toHaveBeenCalledOnce();
  });

  it("runs the latest pending Turn after an in-flight generation fails", async () => {
    let rejectFirst: (reason?: unknown) => void = () => undefined;
    const first = new Promise<string>((_resolve, reject) => {
      rejectFirst = reject;
    });
    const generate = vi.fn()
      .mockImplementationOnce(async () => first)
      .mockResolvedValueOnce("Second Turn Alpha");
    const storeGeneratedTitle = vi.fn(async () => true);
    const generator = new SessionTitleGenerator({ storeGeneratedTitle }, generate);
    const request = {
      languageModel: new ScriptedLanguageModel("scripted-v1"),
      message: "First accepted Turn.",
      providerOptions: {},
      researcherId: "00000000-0000-4000-8000-000000000001",
      threadId: "00000000-0000-4000-8000-000000000111",
    };

    generator.schedule(request);
    generator.schedule({ ...request, message: "Second accepted Turn." });
    rejectFirst(new Error("private provider detail"));
    await generator.settled();

    expect(generate).toHaveBeenCalledTimes(2);
    expect(generate.mock.calls[1]?.[0]).toMatchObject({
      message: "Second accepted Turn.",
    });
    expect(storeGeneratedTitle).toHaveBeenCalledOnce();
    expect(storeGeneratedTitle).toHaveBeenCalledWith(
      request.threadId,
      request.researcherId,
      "Second Turn Alpha",
    );
  });

  it("runs the latest pending Turn when the first generated title is not stored", async () => {
    let resolveFirst: (title: string) => void = () => undefined;
    const first = new Promise<string>((resolve) => {
      resolveFirst = resolve;
    });
    const generate = vi.fn()
      .mockImplementationOnce(async () => first)
      .mockResolvedValueOnce("Second Turn Alpha");
    const storeGeneratedTitle = vi.fn()
      .mockResolvedValueOnce(false)
      .mockResolvedValueOnce(true);
    const generator = new SessionTitleGenerator({ storeGeneratedTitle }, generate);
    const request = {
      languageModel: new ScriptedLanguageModel("scripted-v1"),
      message: "First accepted Turn.",
      providerOptions: {},
      researcherId: "00000000-0000-4000-8000-000000000001",
      threadId: "00000000-0000-4000-8000-000000000111",
    };

    generator.schedule(request);
    generator.schedule({ ...request, message: "Second accepted Turn." });
    resolveFirst("First Turn Alpha");
    await generator.settled();

    expect(generate).toHaveBeenCalledTimes(2);
    expect(storeGeneratedTitle).toHaveBeenNthCalledWith(
      1,
      request.threadId,
      request.researcherId,
      "First Turn Alpha",
    );
    expect(storeGeneratedTitle).toHaveBeenNthCalledWith(
      2,
      request.threadId,
      request.researcherId,
      "Second Turn Alpha",
    );
  });
});
