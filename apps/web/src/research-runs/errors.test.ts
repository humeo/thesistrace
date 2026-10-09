import { expect, test } from "vitest";
import { readCancelError, readTrackingError, formatRunError, formatExecutionFailure, readOrganizationError, readBatchCancelError } from "./errors";
import { i18n } from "../i18n";

test("tracking errors use the actual configured bound and re-render without server sentence parsing", async () => {
  const error = await readTrackingError(Response.json({ detail: { code: "ACTIVE_DAILY_TRACK_LIMIT_REACHED", limit: 7 } }, { status: 409 }));
  expect(formatRunError(error)).toContain("limit is 7");
  await i18n.changeLanguage("zh-CN");
  expect(formatRunError(error)).toContain("上限为 7");
  await i18n.changeLanguage("en");
  for (const detail of ["Active DailyTrack limit of 3 reached", { code: "ACTIVE_DAILY_TRACK_LIMIT_REACHED" }, { code: "ACTIVE_DAILY_TRACK_LIMIT_REACHED", limit: -1 }, { code: "unknown" }]) {
    expect(await readTrackingError(Response.json({ detail }, { status: 409 }))).toEqual({ code: "trackingError" });
  }
  expect(await readTrackingError(Response.json({ detail: { code: "ACTIVE_DAILY_TRACK_LIMIT_REACHED", limit: 0 } }, { status: 409 }))).toEqual({ code: "trackingLimit", limit: 0 });
});

test("cancellation causes are stable codes and unknown details stay private", async () => {
  expect(await readCancelError(Response.json({ detail: { code: "BATCH_CANCELLATION_REQUIRED" } }, { status: 409 }))).toBe("cancelBatch");
  expect(await readCancelError(Response.json({ detail: "private worker diagnostic" }, { status: 500 }))).toBe("cancelError");
});


test("obsolete Python tracking explains how to continue while keeping historical results", async () => {
  const error = await readTrackingError(Response.json({ detail: { code: "TRACKING_PROGRAM_ENVIRONMENT_OBSOLETE" } }, { status: 409 }));
  expect(error).toEqual({ code: "trackingProgram" });
  expect(formatRunError(error)).toContain("new draft");
  await i18n.changeLanguage("zh-CN");
  expect(formatRunError(error)).toContain("新草稿");
  await i18n.changeLanguage("en");
});


test("known execution failures retain their cause while unrecognized diagnostics remain private", async () => {
  expect(formatExecutionFailure("CheckpointIntegrityFailure")).toContain("integrity verification");
  await i18n.changeLanguage("zh-CN");
  expect(formatExecutionFailure("CheckpointIntegrityFailure")).toBe("执行检查点未通过完整性验证。");
  expect(formatExecutionFailure("password=private")).not.toContain("private");
  await i18n.changeLanguage("en");
});

test("public Python failures explain timeout and retain the failing date and author error", async () => {
  const timeout = "PYTHON_EXECUTION_TIMEOUT: program d57e161165ea on 2023-09-01: PythonExecutionTimeout: computation budget exceeded";
  const invalid = "program 77f900359c48 on 2023-09-06, line 12: ValueError: weights must be positive";
  await i18n.changeLanguage("zh-CN");
  expect(formatExecutionFailure(timeout)).toContain("Python 执行超时");
  expect(formatExecutionFailure(timeout)).toContain("2023-09-01");
  expect(formatExecutionFailure(invalid)).toContain("weights must be positive");
  expect(formatExecutionFailure("private worker error: Python program exceeded its wall time limit")).toBe("研究执行失败。");
  await i18n.changeLanguage("en");
  expect(formatExecutionFailure(timeout)).toContain("Python execution timed out");
  expect(formatExecutionFailure(invalid)).toContain("line 12");
  const authorMessage = "program d57e161165ea on 2023-09-01: ValueError: Python program exceeded its wall time limit";
  expect(formatExecutionFailure(authorMessage)).toContain("Python program failed");
  expect(formatExecutionFailure(authorMessage)).not.toContain("Python execution timed out");
  expect(formatExecutionFailure("PYTHON_EXECUTION_TIMEOUT: private worker error")).toBe("Research execution failed.");
  for (const errorType of ["_ValidationError", "策略错误"]) {
    expect(formatExecutionFailure(`program 77f900359c48, line 12: ${errorType}: invalid weight`)).toContain(`${errorType}: invalid weight`);
  }
});


test("folder and batch rejections retain distinct reasons and malformed conflicts stay generic", async () => {
  expect(await readOrganizationError(Response.json({ detail: { code: "FOLDER_NOT_FOUND" } }, { status: 409 }))).toEqual({ code: "folderMissing" });
  expect(await readBatchCancelError(Response.json({ detail: { code: "BATCH_NOT_CANCELLABLE" } }, { status: 409 }))).toBe("cancelConflict");
  expect(await readBatchCancelError(Response.json({ detail: { code: "BATCH_CANCEL_REQUEST_CONFLICT" } }, { status: 409 }))).toBe("cancelRequestConflict");
  for (const detail of ["Research Batch state does not allow cancellation", {}, { code: "PRIVATE_FAILURE" }]) {
    expect(await readBatchCancelError(Response.json({ detail }, { status: 409 }))).toBe("cancelError");
  }
});
