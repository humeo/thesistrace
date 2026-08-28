import { describe, expect, it } from "vitest";

import {
  AuthSchemaContractError,
  assertExactCatalog,
  catalogFingerprint,
  type AuthSchemaCatalog,
} from "./schema-contract.js";

const catalog: AuthSchemaCatalog = {
  columns: [
    {
      default: null,
      name: "singleton",
      notNull: true,
      position: 1,
      relation: "schema_contract",
      type: "boolean",
    },
  ],
  constraints: [],
  indexes: [],
  policies: [],
  relations: [
    {
      forceRowSecurity: false,
      kind: "r",
      name: "schema_contract",
      owner: "thesistrace_owner",
      persistence: "p",
      rowSecurity: false,
    },
  ],
  routines: [],
  schema: { owner: "thesistrace_owner" },
  triggers: [],
  types: [],
};

describe("Auth schema contract", () => {
  it("accepts only an exact physical catalog", () => {
    expect(() => assertExactCatalog(catalog, structuredClone(catalog))).not.toThrow();

    expect(() =>
      assertExactCatalog(catalog, { ...catalog, relations: [] }),
    ).toThrow(AuthSchemaContractError);
    expect(() =>
      assertExactCatalog(catalog, {
        ...catalog,
        relations: [
          ...catalog.relations,
          {
            forceRowSecurity: false,
            kind: "r",
            name: "unexpected",
            owner: "thesistrace_owner",
            persistence: "p",
            rowSecurity: false,
          },
        ],
      }),
    ).toThrow(AuthSchemaContractError);
    expect(() =>
      assertExactCatalog(catalog, {
        ...catalog,
        relations: [{ ...catalog.relations[0], rowSecurity: true }],
      }),
    ).toThrow(AuthSchemaContractError);
    expect(() =>
      assertExactCatalog(catalog, {
        ...catalog,
        relations: [{ ...catalog.relations[0], persistence: "u" }],
      }),
    ).toThrow(AuthSchemaContractError);
    expect(() =>
      assertExactCatalog(catalog, {
        ...catalog,
        routines: [
          {
            configuration: [],
            identityArguments: "",
            kind: "f",
            language: "sql",
            leakproof: false,
            name: "unexpected",
            owner: "thesistrace_owner",
            parallel: "u",
            result: "void",
            securityDefiner: false,
            source: "SELECT NULL",
            strict: false,
            volatility: "v",
          },
        ],
      }),
    ).toThrow(AuthSchemaContractError);
    expect(() =>
      assertExactCatalog(catalog, {
        ...catalog,
        columns: [{ ...catalog.columns[0], type: "text" }],
      }),
    ).toThrow(AuthSchemaContractError);
  });

  it("uses one deterministic SHA-256 fingerprint for the committed catalog", () => {
    expect(catalogFingerprint(catalog)).toMatch(/^[0-9a-f]{64}$/);
    expect(catalogFingerprint(structuredClone(catalog))).toBe(
      catalogFingerprint(catalog),
    );
    expect(catalogFingerprint({ ...catalog, relations: [] })).not.toBe(
      catalogFingerprint(catalog),
    );
  });

  it("never exposes catalog details in its public error", () => {
    let thrown: unknown;
    try {
      assertExactCatalog(catalog, { ...catalog, relations: [] });
    } catch (error) {
      thrown = error;
    }

    expect(thrown).toBeInstanceOf(AuthSchemaContractError);
    expect((thrown as Error).message).toBe("AUTH_SCHEMA_CONTRACT_INVALID");
    expect((thrown as Error).message).not.toContain("schema_contract");
  });
});
