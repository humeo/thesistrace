import type { JsonSchemaType, JsonSchemaValidator, jsonSchemaValidator } from "@modelcontextprotocol/client";
import { AjvJsonSchemaValidator } from "@modelcontextprotocol/client/validators/ajv";

/** Cache only compiled schema content; connections, credentials and results stay per Run. */
export class McpSchemaValidator implements jsonSchemaValidator {
  private readonly validators = new Map<string, JsonSchemaValidator<unknown>>();

  getValidator<T>(schema: JsonSchemaType): JsonSchemaValidator<T> {
    const key = JSON.stringify(schema);
    const existing = this.validators.get(key);
    if (existing) return existing as JsonSchemaValidator<T>;
    // Own the schema snapshot and its engine: a reused $id with changed content
    // must not select another Run's old schema from AJV's id-based registry.
    const validator = new AjvJsonSchemaValidator().getValidator<T>(JSON.parse(key));
    if (this.validators.size === 128) this.validators.delete(this.validators.keys().next().value!);
    this.validators.set(key, validator);
    return validator;
  }
}
