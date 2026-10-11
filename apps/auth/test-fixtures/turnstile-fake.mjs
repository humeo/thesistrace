// Explicit isolated-test provider; never loaded by the application image.
const consumed = new Map();
export async function handleTurnstileFake(request, response) {
  const url = new URL(request.url ?? "/", "http://resend-fake.test");
  if (request.method !== "POST" || url.pathname !== "/turnstile/v0/siteverify") return false;
  let raw = "";
  for await (const chunk of request) {raw += chunk; if (raw.length > 8192) break;}
  const form = new URLSearchParams(raw);
  const token = form.get("response") ?? "";
  const [prefix, hostname, issuedAt, nonce] = token.split(":");
  const now = Date.now();
  for (const [key, expires] of consumed) if (expires < now) consumed.delete(key);
  const success = form.get("secret") === "1x0000000000000000000000000000000AA"
    && prefix === "test-turnstile" && Boolean(hostname) && /^[0-9a-f-]{36}$/.test(nonce ?? "")
    && Number.isSafeInteger(Number(issuedAt)) && Number(issuedAt) <= now && now - Number(issuedAt) < 300000 && !consumed.has(token);
  if (success) consumed.set(token, now + 300000);
  response.writeHead(200, {"content-type":"application/json"});
  response.end(JSON.stringify({success, ...(success ? {hostname, action:"sign-in-code"} : {"error-codes":["timeout-or-duplicate"]})}));
  return true;
}
