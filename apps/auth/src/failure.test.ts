import { describe, expect, it } from "vitest";

import {
  AuthConfigurationError,
  AuthSchemaContractError,
  diagnoseAuthFailure,
} from "./failure.js";

describe("sanitized Auth diagnostics", () => {
  it("distinguishes configuration and schema contract failures", () => {
    expect(diagnoseAuthFailure(new AuthConfigurationError("private-value"))).toEqual({
      reason: "CONFIGURATION_INVALID",
    });
    expect(
      diagnoseAuthFailure(
        new AuthSchemaContractError("SCHEMA_FINGERPRINT_MISMATCH"),
      ),
    ).toEqual({ reason: "SCHEMA_FINGERPRINT_MISMATCH" });
  });

  it("reports only a stable reason and valid PostgreSQL SQLSTATE", () => {
    const diagnostic = diagnoseAuthFailure(
      Object.assign(new Error("password=do-not-log"), { code: "42501" }),
    );

    expect(diagnostic).toEqual({
      reason: "DATABASE_PERMISSION_DENIED",
      sqlstate: "42501",
    });
    expect(JSON.stringify(diagnostic)).not.toContain("password=do-not-log");
  });

  it("classifies connection failures without reflecting their details", () => {
    for (const code of ["ECONNREFUSED", "ENOTFOUND", "EAI_AGAIN"]) {
      expect(
        diagnoseAuthFailure(
          Object.assign(new Error("postgresql://private"), { code }),
        ),
      ).toEqual({ reason: "DATABASE_UNAVAILABLE" });
    }
    for (const message of [
      "Connection terminated due to connection timeout",
      "timeout exceeded when trying to connect",
    ]) {
      expect(diagnoseAuthFailure(new Error(message))).toEqual({
        reason: "DATABASE_UNAVAILABLE",
      });
    }
    expect(diagnoseAuthFailure(new Error("Query read timeout"))).toEqual({
      reason: "DATABASE_OPERATION_FAILED",
    });
    expect(
      diagnoseAuthFailure(
        Object.assign(new Error("terminating connection"), { code: "57P01" }),
      ),
    ).toEqual({ reason: "DATABASE_UNAVAILABLE", sqlstate: "57P01" });
  });
});
