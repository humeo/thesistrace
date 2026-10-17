import { expect, test } from "vitest";
import { i18n } from "./index";

test("billing messages load with their routes and follow the selected language", async () => {
  expect(i18n.hasResourceBundle("en", "billing")).toBe(false);
  expect(i18n.hasResourceBundle("zh-CN", "billing")).toBe(false);
  await import("./billing");
  try {
    await i18n.changeLanguage("en");
    expect(i18n.t("billing:title")).toBe("Plan and billing");
    expect(i18n.t("billing:trackAmount", { count: 10 })).toBe("10 tracking slots");
    await i18n.changeLanguage("zh-CN");
    expect(i18n.t("billing:title")).toBe("套餐与账单");
    expect(i18n.t("billing:trackAmount", { count: 1 })).toBe("1 个跟踪名额");
  } finally {
    await i18n.changeLanguage("en");
  }
});
