import { type FormEvent, type ReactNode, useEffect, useState } from "react";

type AuthMode = "detecting" | "v1" | "login" | "register" | "verify" | "recover";

type Session = {
  product_state: "non_provisioned" | "provisioned";
  identity: { email: string };
  workspace_id?: string;
};

let accessToken: string | null = null;

function authHeaders(headers?: HeadersInit): Headers {
  const result = new Headers(headers);
  if (accessToken !== null) {
    result.set("Authorization", `Bearer ${accessToken}`);
  }
  return result;
}

export function apiFetch(input: RequestInfo | URL, init: RequestInit = {}) {
  return globalThis.fetch(input, { ...init, headers: authHeaders(init.headers) });
}

async function jsonRequest(
  path: string,
  init: RequestInit = {},
): Promise<{ response: Response; payload: Record<string, unknown> }> {
  const response = await globalThis.fetch(path, {
    ...init,
    headers: new Headers({
      Accept: "application/json",
      ...(init.body === undefined ? {} : { "Content-Type": "application/json" }),
      ...Object.fromEntries(new Headers(init.headers).entries()),
    }),
  });
  let payload: Record<string, unknown> = {};
  try {
    payload = (await response.json()) as Record<string, unknown>;
  } catch {
    // The status remains the public contract when a proxy returns no JSON.
  }
  return { response, payload };
}

function errorMessage(payload: Record<string, unknown>, fallback: string): string {
  const detail = payload.detail;
  if (typeof detail === "object" && detail !== null) {
    const reason = (detail as Record<string, unknown>).reason_code;
    if (typeof reason === "string") {
      return reason;
    }
  }
  return fallback;
}

export function HostedAuthBoundary({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<AuthMode>("detecting");
  const [session, setSession] = useState<Session | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [verificationCode, setVerificationCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [recoveryCodeRequested, setRecoveryCodeRequested] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadSession(token: string): Promise<Session> {
    accessToken = token;
    const response = await apiFetch("/api/v1/session");
    if (!response.ok) {
      accessToken = null;
      throw new Error("AUTH_SESSION_UNAVAILABLE");
    }
    return (await response.json()) as Session;
  }

  useEffect(() => {
    let active = true;
    void globalThis.fetch("/api/v1/session", { headers: { Accept: "application/json" } }).then(
      async (response) => {
        if (!active) return;
        if (response.status === 404) {
          setMode("v1");
        } else {
          setMode("login");
        }
      },
      () => {
        if (active) setMode("login");
      },
    );
    return () => {
      active = false;
    };
  }, []);

  async function login(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { response, payload } = await jsonRequest(
        "/api/auth/sessions?client_type=server",
        { method: "POST", body: JSON.stringify({ email, password }) },
      );
      const token = payload.accessToken;
      if (!response.ok || typeof token !== "string") {
        throw new Error(errorMessage(payload, "AUTH_LOGIN_FAILED"));
      }
      setSession(await loadSession(token));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "AUTH_LOGIN_FAILED");
    } finally {
      setBusy(false);
    }
  }

  async function register(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const anon = await jsonRequest("/api/auth/anon-key");
      const anonKey = anon.payload.anonKey;
      if (!anon.response.ok || typeof anonKey !== "string") {
        throw new Error("AUTH_ANON_KEY_UNAVAILABLE");
      }
      const { response, payload } = await jsonRequest(
        "/api/auth/users?client_type=server",
        {
          method: "POST",
          headers: { Authorization: `Bearer ${anonKey}` },
          body: JSON.stringify({ email, password, name: "ThesisTrace User" }),
        },
      );
      if (!response.ok) {
        throw new Error(errorMessage(payload, "AUTH_REGISTRATION_FAILED"));
      }
      setMode("verify");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "AUTH_REGISTRATION_FAILED");
    } finally {
      setBusy(false);
    }
  }

  async function verify(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { response, payload } = await jsonRequest(
        "/api/auth/email/verify?client_type=server",
        {
          method: "POST",
          body: JSON.stringify({ email, otp: verificationCode }),
        },
      );
      const token = payload.accessToken;
      if (!response.ok || typeof token !== "string") {
        throw new Error(errorMessage(payload, "AUTH_VERIFICATION_FAILED"));
      }
      setSession(await loadSession(token));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "AUTH_VERIFICATION_FAILED");
    } finally {
      setBusy(false);
    }
  }

  async function recover(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (!recoveryCodeRequested) {
        const sent = await jsonRequest("/api/auth/email/send-reset-password", {
          method: "POST",
          body: JSON.stringify({ email }),
        });
        if (sent.response.status !== 202) {
          throw new Error(errorMessage(sent.payload, "AUTH_RECOVERY_FAILED"));
        }
        setRecoveryCodeRequested(true);
        return;
      }
      const exchanged = await jsonRequest(
        "/api/auth/email/exchange-reset-password-token",
        {
          method: "POST",
          body: JSON.stringify({ email, code: verificationCode.trim() }),
        },
      );
      const resetToken = exchanged.payload.token;
      if (!exchanged.response.ok || typeof resetToken !== "string") {
        throw new Error(errorMessage(exchanged.payload, "AUTH_RECOVERY_CODE_INVALID"));
      }
      const reset = await jsonRequest("/api/auth/email/reset-password", {
        method: "POST",
        body: JSON.stringify({ newPassword, otp: resetToken }),
      });
      if (!reset.response.ok) {
        throw new Error(errorMessage(reset.payload, "AUTH_PASSWORD_RESET_FAILED"));
      }
      setPassword(newPassword);
      setVerificationCode("");
      setNewPassword("");
      setRecoveryCodeRequested(false);
      setMode("login");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "AUTH_RECOVERY_FAILED");
    } finally {
      setBusy(false);
    }
  }

  async function provision() {
    setBusy(true);
    setError(null);
    try {
      const response = await apiFetch("/api/v1/provision", { method: "POST" });
      if (!response.ok) throw new Error("PRODUCT_PROVISIONING_FAILED");
      const current = await apiFetch("/api/v1/session");
      if (!current.ok) throw new Error("AUTH_SESSION_UNAVAILABLE");
      setSession((await current.json()) as Session);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "PRODUCT_PROVISIONING_FAILED");
    } finally {
      setBusy(false);
    }
  }

  if (mode === "detecting") {
    return <main className="auth-shell">正在识别运行环境…</main>;
  }
  if (mode === "v1") {
    return children;
  }
  if (session?.product_state === "provisioned") {
    return (
      <>
        <div className="hosted-session-bar">
          <span>{session.identity.email}</span>
          <span>Personal Workspace · {session.workspace_id}</span>
          <button
            type="button"
            onClick={() => {
              accessToken = null;
              setSession(null);
              setMode("login");
            }}
          >
            退出登录
          </button>
        </div>
        {children}
      </>
    );
  }
  if (session?.product_state === "non_provisioned") {
    return (
      <main className="auth-shell">
        <section className="auth-card">
          <p className="eyebrow">HOSTED V2</p>
          <h1>创建 Personal Workspace</h1>
          <p>{session.identity.email}</p>
          {error && <p role="alert">{error}</p>}
          <button type="button" disabled={busy} onClick={() => void provision()}>
            创建唯一的 Personal Workspace
          </button>
        </section>
      </main>
    );
  }

  const submit =
    mode === "register"
      ? register
      : mode === "verify"
        ? verify
        : mode === "recover"
          ? recover
          : login;
  return (
    <main className="auth-shell">
      <section className="auth-card">
        <p className="eyebrow">THESISTRACE HOSTED</p>
        <h1>
          {mode === "register"
            ? "注册受邀用户"
            : mode === "verify"
              ? "验证邮箱"
              : mode === "recover"
                ? "恢复密码"
                : "登录 Personal Workspace"}
        </h1>
        <form onSubmit={(event) => void submit(event)}>
          <label>
            邮箱
            <input type="email" value={email} required onChange={(event) => setEmail(event.target.value)} />
          </label>
          {(mode === "login" || mode === "register") && (
            <label>
              密码
              <input type="password" value={password} required onChange={(event) => setPassword(event.target.value)} />
            </label>
          )}
          {mode === "verify" && (
            <label>
              邮箱验证码
              <input value={verificationCode} required onChange={(event) => setVerificationCode(event.target.value)} />
            </label>
          )}
          {mode === "recover" && recoveryCodeRequested && (
            <>
              <label>
                重置验证码
                <input value={verificationCode.trim()} required onChange={(event) => setVerificationCode(event.target.value)} />
              </label>
              <label>
                新密码
                <input type="password" value={newPassword} required onChange={(event) => setNewPassword(event.target.value)} />
              </label>
            </>
          )}
          {error && <p role="alert">{error}</p>}
          <button type="submit" disabled={busy}>
            {busy
              ? "处理中…"
              : mode === "recover" && !recoveryCodeRequested
                ? "发送恢复邮件"
                : "继续"}
          </button>
        </form>
        <nav className="auth-switcher" aria-label="身份流程">
          <button type="button" onClick={() => { setMode("login"); setError(null); }}>登录</button>
          <button type="button" onClick={() => { setMode("register"); setError(null); }}>注册</button>
          <button type="button" onClick={() => { setMode("recover"); setError(null); setVerificationCode(""); setRecoveryCodeRequested(false); }}>忘记密码</button>
        </nav>
      </section>
    </main>
  );
}
