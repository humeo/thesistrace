import { describe, expect, test, vi } from "vitest";
import { initialInterfaceLocale, LANGUAGE_PREFERENCE_KEY, rememberInterfaceLocale } from "./language";

describe("interface language at a public or product entry", () => {
  test.each([
    ["/", "", null, "en"],
    ["/data", "", "zh-CN", "zh-CN"],
    ["/research", "", "en", "en"],
    ["/", "?lang=zh", "en", "zh-CN"],
    ["/login", "?lang=zh&returnTo=%2Fresearch", "en", "zh-CN"],
    ["/accept-invitation", "?lang=zh", null, "zh-CN"],
    ["/", "?lang=en", "zh-CN", "en"],
    ["/", "?lang=unknown", "zh-CN", "zh-CN"],
    ["/", "", "unsupported", "en"],
    ["/data", "?lang=zh", "en", "en"],
    ["/login", "?sig=signed&lang=zh", "en", "en"],
  ] as const)("%s%s resolves stored %s to %s", (pathname, search, saved, expected) => {
    const storage = { getItem: () => saved, setItem: vi.fn() };
    expect(initialInterfaceLocale({ pathname, search }, storage)).toBe(expected);
    expect(storage.setItem).not.toHaveBeenCalled();
  });

  test("unavailable storage does not prevent a public language choice", () => {
    const storage = { getItem() { throw new Error("Storage denied"); } };
    expect(initialInterfaceLocale({ pathname: "/", search: "" }, storage)).toBe("en");
    expect(initialInterfaceLocale({ pathname: "/", search: "?lang=zh" }, storage)).toBe("zh-CN");
  });

  test("saves an explicit choice for the next product load", () => {
    const values = new Map<string, string>();
    const storage = { getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); } };
    rememberInterfaceLocale("zh-CN", storage);
    expect(values.get(LANGUAGE_PREFERENCE_KEY)).toBe("zh-CN");
    expect(initialInterfaceLocale({ pathname: "/data", search: "" }, storage)).toBe("zh-CN");
    expect(() => rememberInterfaceLocale("en", { setItem() { throw new Error("Storage denied"); } })).not.toThrow();
  });
});
