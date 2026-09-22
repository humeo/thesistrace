import { expect, test } from "vitest";
import { resources } from "./resources";

function messages(value: unknown, path = ""): Map<string, string> {
  if (typeof value === "string") return new Map([[path, value]]);
  if (value === null || typeof value !== "object") throw new Error(`Invalid translation at ${path}`);
  return new Map(Object.entries(value).flatMap(([key, child]) => [...messages(child, `${path}.${key}`)]));
}

function parameters(message: string): string[] {
  return [...message.matchAll(/\{\{\s*([^},]+)(?:,[^}]+)?\s*\}\}/g)].map(match => match[1].trim()).sort();
}

test("both bundled languages cover the same messages and interpolation parameters", () => {
  const english = messages(resources.en);
  const chinese = messages(resources["zh-CN"]);
  expect([...chinese.keys()].sort()).toEqual([...english.keys()].sort());
  for (const [key, text] of english) {
    expect(text.trim(), key).not.toBe("");
    expect(chinese.get(key)?.trim(), key).not.toBe("");
    expect(parameters(chinese.get(key)!), key).toEqual(parameters(text));
  }
});
