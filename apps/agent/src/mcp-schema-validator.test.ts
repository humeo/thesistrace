import { expect, it } from "vitest";
import { McpSchemaValidator } from "./mcp-schema-validator.js";

it("keeps validation and errors independent across repeated schemas and inputs", () => {
  const provider = new McpSchemaValidator();
  const schema = { type: "object", properties: { count: { type: "integer" } }, required: ["count"] };
  const first = provider.getValidator(schema);
  const second = provider.getValidator(structuredClone(schema));
  const rejected = first({ count: "wrong" });
  expect(rejected.valid).toBe(false);
  expect(second({ count: 3 })).toMatchObject({ valid: true, data: { count: 3 } });
  expect(rejected.valid).toBe(false);
  expect(rejected.errorMessage).toContain("integer");
  expect(second({})).toMatchObject({ valid: false });
});

it("validates changed schema content even when its id is reused, without changing an existing validator", () => {
  const provider = new McpSchemaValidator();
  const schema = { $id: "https://schema.fixture/result", type: "integer" };
  const original = provider.getValidator(schema);
  schema.type = "string";
  const revised = provider.getValidator(schema);
  expect(original(2).valid).toBe(true);
  expect(original("two").valid).toBe(false);
  expect(revised("two").valid).toBe(true);
  expect(revised(2).valid).toBe(false);
});

it("preserves the SDK dialect and format rules", () => {
  const provider = new McpSchemaValidator();
  const validator = provider.getValidator({ type: "string", format: "date" });
  expect(validator("2026-02-28").valid).toBe(true);
  expect(validator("2026-02-30").valid).toBe(false);
  expect(() => provider.getValidator({ $schema: "https://schema.fixture/unsupported", type: "string" })).toThrow();
});
