// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, test, vi } from "vitest";
import { changeInterfaceLanguage } from "../i18n";
import { AuthRoute } from "./AuthPages";

vi.mock("./AuthProvider", () => ({ useAuth: () => ({
  sendCode: async () => ({ ok: false, code: "codeDeliveryFailed" }),
}) }));
(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

test("an existing authentication error follows the interface language without resubmitting", async () => {
  changeInterfaceLanguage("en");
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  try {
    await act(async () => root.render(<AuthRoute clearSecret={() => {}} secret={null}
      location={{ pathname: "/login", search: "", hash: "" }} navigate={() => {}} />));
    const emailInput = container.querySelector("input");
    await act(async () => container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    expect(container.querySelector('[role="alert"]')?.textContent).toBe("The verification code could not be sent. Please try again.");
    await act(async () => changeInterfaceLanguage("zh-CN"));
    expect(container.querySelector('[role="alert"]')?.textContent).toBe("未能发送验证码，请重试。");
    expect(container.querySelector("input")).toBe(emailInput);
    expect(container.querySelector("h1")?.textContent).toBe("欢迎来到 Quantgrove");
    expect(document.documentElement.lang).toBe("zh-CN");
  } finally {
    await act(async () => root.unmount());
    container.remove();
    changeInterfaceLanguage("en");
  }
});
