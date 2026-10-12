import { describe, expect, test } from "vitest";

import {
  isAuthPath,
  isProductPath,
  locationHref,
  safeReturnTo,
  type BrowserLocation,
} from "./routing";

describe("browser auth routing", () => {
  test("retains pathname, search, and ordinary product hash", () => {
    const location: BrowserLocation = {
      pathname: "/research",
      search: "?folder=folder_signals",
      hash: "#formula",
    };

    expect(locationHref(location)).toBe(
      "/research?folder=folder_signals#formula",
    );
  });

  test.each([
    "/login",
  ])("recognizes the Auth route %s", (pathname) => {
    expect(isAuthPath(pathname)).toBe(true);
    expect(isProductPath(pathname)).toBe(false);
  });

  test.each([
    "/chat",
    "/data",
    "/research",
    "/research-runs/run_feedface",
    "/research-runs/batches",
    "/research-runs/batches/batch_feedface",
    "/daily-tracks/track_feedface",
    "/operator/researchers",
    "/operator/data",
  ])("recognizes the product route %s", (pathname) => {
    expect(isProductPath(pathname)).toBe(true);
    expect(isAuthPath(pathname)).toBe(false);
  });

  test.each([
    ["/chat", "/chat"],
    ["/research?folder=folder_default#formula", "/research?folder=folder_default#formula"],
    ["/research-runs/run_feedface", "/research-runs/run_feedface"],
    ["/research-runs/batches", "/research-runs/batches"],
    ["/research-runs/batches/batch_feedface", "/research-runs/batches/batch_feedface"],
    ["/operator/researchers", "/operator/researchers"],
    ["/operator/data", "/operator/data"],
    ["//attacker.test/data", null],
    ["https://attacker.test/data", null],
    ["/login?returnTo=%2Fdata", null],
    ["/unknown", null],
    ["/data\\@attacker.test", null],
  ])("validates returnTo %s", (candidate, expected) => {
    expect(safeReturnTo(candidate, "https://thesistrace.test")).toBe(expected);
  });
});
