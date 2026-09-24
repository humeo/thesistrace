import { expect, test } from "vitest";
import { formatResearchIssue, readResearchIssues, type ResearchRunAdmissionIssue } from "./admission";
import { folderDisplayName, folderMutationError } from "./folders";

test("only stable system folder identities receive translated names", () => {
  expect(folderDisplayName({ id: "folder_default", name: "Default" }, "zh-CN")).toBe("默认");
  expect(folderDisplayName({ id: "folder_batch_research", name: "Batch Research" }, "zh-CN")).toBe("批量研究");
  for (const name of ["Default", "Batch Research", "未命名"]) {
    expect(folderDisplayName({ id: "folder_custom", name }, "zh-CN")).toBe(name);
    expect(folderDisplayName({ id: "folder_custom", name }, "en")).toBe(name);
  }
});

test("folder rejections retain their distinct causes without interpreting server text", async () => {
  for (const [code, expected] of [
    ["SYSTEM_FOLDER_RENAME_FORBIDDEN", "systemRename"],
    ["SYSTEM_FOLDER_DELETE_FORBIDDEN", "systemDelete"], ["FOLDER_NOT_EMPTY", "nonempty"],
    ["UNKNOWN_CODE", "unavailable"],
  ]) expect(await folderMutationError(Response.json({ detail: { code } }, { status: 409 }))).toBe(expected);
  expect(await folderMutationError(Response.json({ detail: "private server message" }, { status: 409 }))).toBe("unavailable");
  expect(await folderMutationError(new Response("not JSON", { status: 409 }))).toBe("unavailable");
});

const issue = (code: string, details: ResearchRunAdmissionIssue["details"]): ResearchRunAdmissionIssue => ({
  code, details, field: "start_date", message: "private server text", severity: "error", range: null,
});

test("configuration errors preserve quota, timezone, coverage and warmup facts in both languages", () => {
  const quota = issue("DAILY_RUN_QUOTA_EXCEEDED", { kind: "quota", expected: 7, actual: "Asia/Shanghai" });
  expect(formatResearchIssue(quota, "en")).toBe("Daily ResearchRun submission limit of 7 reached. Resets at 00:00 Asia/Shanghai.");
  expect(formatResearchIssue(quota, "zh-CN")).toBe("已达到每日 7 次研究运行提交上限，将于 Asia/Shanghai 00:00 重置。");
  const coverage = issue("INDUSTRY_CALCULATION_OUTSIDE_COVERAGE", {
    kind: "coverage", expected: "equity.industry_membership", actual: ["2026-08-05", "2026-08-07"],
  });
  expect(formatResearchIssue(coverage, "en")).toBe("Formula requires industry membership coverage for its calculation period; current coverage is 2026-08-05 to 2026-08-07.");
  expect(formatResearchIssue(coverage, "zh-CN")).toBe("公式计算期间需要行业成员关系数据覆盖；当前覆盖范围为 2026-08-05 至 2026-08-07。");
  const warmup = issue("INSUFFICIENT_CALCULATION_WARMUP", { kind: "warmup", expected: 5, actual: "2026-08-07" });
  expect(formatResearchIssue(warmup, "en")).toBe("Research Period requires 5 sessions before 2026-08-07.");
  expect(formatResearchIssue(warmup, "zh-CN")).toBe("研究期间需要 2026-08-07 之前的 5 个交易日用于预热。");
});

test("unknown or malformed admission errors never become raw server messages", () => {
  for (const failure of [issue("UNKNOWN", null), issue("DAILY_RUN_QUOTA_EXCEEDED", null)]) {
    expect(formatResearchIssue(failure, "zh-CN")).toBe("研究验证失败，请检查设置后重试。");
    expect(formatResearchIssue(failure, "en")).toBe("Research validation failed. Please check the settings and try again.");
  }
  expect(() => readResearchIssues([{ code: "TYPE_MISMATCH", range: {} }])).toThrow();
  expect(readResearchIssues([issue("FOLDER_NOT_FOUND", null)])).toEqual([issue("FOLDER_NOT_FOUND", null)]);
});

test("Python diagnostics keep their type and line when the interface language changes", () => {
  const syntax = issue("STRATEGY_PROGRAM_INVALID", {
    kind: "strategy_program", error_type: "SyntaxError", line: 1,
  });
  expect(formatResearchIssue(syntax, "en")).toBe("Python syntax error at line 1.");
  expect(formatResearchIssue(syntax, "zh-CN")).toBe("Python 语法错误，第 1 行。");
  expect(formatResearchIssue({ ...syntax, details: null }, "zh-CN")).toBe("研究验证失败，请检查设置后重试。");
});

test("current-data rerun rejections preserve the source-setting and checkpoint causes", () => {
  const [setting, boundary] = readResearchIssues([
    { ...issue("RERUN_SOURCE_INVALID", null), field: "strategy.execution", details: {
      kind: "rerun_source", reason: "unsupported_setting", expected: null, actual: null, validation_type: null,
    } },
    { ...issue("RERUN_SOURCE_INVALID", null), field: "rerun_source.through_session", details: {
      kind: "rerun_source", reason: "checkpoint_boundary", expected: "2026-08-20", actual: "2026-08-21", validation_type: null,
    } },
  ]);
  expect(formatResearchIssue(setting, "en")).toBe("The original simulation setting is unsupported by the current contract.");
  expect(formatResearchIssue(setting, "zh-CN")).toBe("原模拟设置不受当前契约支持。");
  expect(formatResearchIssue(boundary, "en")).toBe("Investigation date 2026-08-21 exceeds the selected published Checkpoint through 2026-08-20.");
  expect(formatResearchIssue(boundary, "zh-CN")).toBe("调查日期 2026-08-21 超过所选已发布检查点的结束日期 2026-08-20。");
});
