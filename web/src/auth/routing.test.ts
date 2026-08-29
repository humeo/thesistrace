import { describe, expect, test } from "vitest";

import {
  extractInitialAuthSecret,
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
    "/accept-invitation",
    "/forgot-password",
    "/reset-password",
  ])("recognizes the Auth route %s", (pathname) => {
    expect(isAuthPath(pathname)).toBe(true);
    expect(isProductPath(pathname)).toBe(false);
  });

  test.each([
    "/data",
    "/research",
    "/research-runs/run_feedface",
    "/daily-tracks/track_feedface",
    "/operator/researchers",
  ])("recognizes the product route %s", (pathname) => {
    expect(isProductPath(pathname)).toBe(true);
    expect(isAuthPath(pathname)).toBe(false);
  });

  test("extracts an Invitation token once and removes the fragment", () => {
    expect(
      extractInitialAuthSecret({
        pathname: "/accept-invitation",
        search: "?returnTo=%2Fresearch",
        hash: "#token=invitation-secret",
      }),
    ).toEqual({
      location: {
        pathname: "/accept-invitation",
        search: "?returnTo=%2Fresearch",
        hash: "",
      },
      secret: { kind: "invitation", token: "invitation-secret" },
    });
  });

  test("clears malformed Reset fragments without retaining them", () => {
    expect(
      extractInitialAuthSecret({
        pathname: "/reset-password",
        search: "",
        hash: "#unexpected=value",
      }),
    ).toEqual({
      location: { pathname: "/reset-password", search: "", hash: "" },
      secret: null,
    });
  });

  test.each([
    ["/research?folder=folder_default#formula", "/research?folder=folder_default#formula"],
    ["/research-runs/run_feedface", "/research-runs/run_feedface"],
    ["/operator/researchers", "/operator/researchers"],
    ["//attacker.test/data", null],
    ["https://attacker.test/data", null],
    ["/login?returnTo=%2Fdata", null],
    ["/unknown", null],
    ["/data\\@attacker.test", null],
  ])("validates returnTo %s", (candidate, expected) => {
    expect(safeReturnTo(candidate, "https://thesistrace.test")).toBe(expected);
  });
});
