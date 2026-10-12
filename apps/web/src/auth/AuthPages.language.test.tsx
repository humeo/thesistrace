// @vitest-environment happy-dom
import { act, useEffect, useImperativeHandle, type RefObject } from "react";
import { createRoot } from "react-dom/client";
import { expect, test, vi } from "vitest";
import { changeInterfaceLanguage } from "../i18n";
import { AuthRoute } from "./AuthPages";

const { sendCode } = vi.hoisted(() => ({ sendCode: vi.fn() }));
vi.mock("./AuthProvider", () => ({ useAuth: () => ({ sendCode }) }));
vi.mock("./SignInChallenge", () => ({
  SignInChallenge: ({onToken, widgetRef}: {
    onToken: (token: string) => void;
    widgetRef: RefObject<{reset: () => void} | null>;
  }) => {
    useEffect(() => onToken("test-browser-verification"), [onToken]);
    useImperativeHandle(widgetRef, () => ({reset: () => onToken("test-browser-verification")}), [onToken]);
    return null;
  },
}));
(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

test("an existing authentication error follows the interface language without resubmitting", async () => {
  sendCode.mockResolvedValue({ok: false, code: "codeDeliveryFailed"});
  changeInterfaceLanguage("en");
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  try {
    await act(async () => root.render(<AuthRoute
      location={{ pathname: "/login", search: "", hash: "" }} />));
    await act(async () => vi.dynamicImportSettled());
    const emailInput = container.querySelector("input");
    await act(async () => container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    expect(container.querySelector('[role="alert"]')?.textContent).toBe("The verification code could not be sent. Please try again.");
    await act(async () => changeInterfaceLanguage("zh-CN"));
    expect(container.querySelector('[role="alert"]')?.textContent).toBe("未能发送验证码，请重试。");
    expect(container.querySelector("input")).toBe(emailInput);
    expect(container.querySelector("h1")?.textContent).toBe("欢迎来到 QAgentis");
    expect(document.documentElement.lang).toBe("zh-CN");
  } finally {
    await act(async () => root.unmount());
    container.remove();
    changeInterfaceLanguage("en");
  }
});


test("shows server cooldown in both languages and enables manual retry at expiry", async () => {
  vi.useFakeTimers({toFake: ["Date", "setInterval", "clearInterval"]});
  sendCode.mockClear();
  sendCode.mockResolvedValue({ok: false, code: "tooManyRequests", retryAfterSeconds: 37});
  changeInterfaceLanguage("en");
  const container = document.createElement("div"); document.body.append(container);
  const root = createRoot(container);
  try {
    await act(async () => root.render(<AuthRoute  location={{pathname: "/login", search: "", hash: ""}} />));
    await act(async () => vi.dynamicImportSettled());
    await act(async () => container.querySelector("form")!.dispatchEvent(new Event("submit", {bubbles: true, cancelable: true})));
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("37s");
    expect(container.querySelector('button[type="submit"]')?.hasAttribute("disabled")).toBe(true);
    await act(async () => changeInterfaceLanguage("zh-CN"));
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("37 秒");
    await act(async () => vi.advanceTimersByTime(37_000));
    expect(container.querySelector('button[type="submit"]')?.hasAttribute("disabled")).toBe(false);
    expect(sendCode).toHaveBeenCalledTimes(1);
  } finally { await act(async () => root.unmount()); container.remove(); vi.useRealTimers(); changeInterfaceLanguage("en"); }
});
