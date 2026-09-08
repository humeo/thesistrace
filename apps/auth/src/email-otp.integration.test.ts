import { OperatorEmailCode } from "./operator-email-code.js";
import { OperatorAssignmentService } from "./operator-assignment.js";
import { OperatorProofService, OperatorCodeInvalidError, OperatorProofInvalidError } from "./operator-proof.js";
import { EmailCodeDelivery } from "./email-code.js";
import { AuthEndpointRateLimiter } from "./auth-rate-limit.js";
import { Pool } from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { createThesisTraceAuth, createClosedAuthLifecycle } from "./auth.js";
import { createAuthApp, type AuthAppDependencies } from "./app.js";
import { authTestSettings } from "../test-fixtures/auth-settings.js";
import { AuthOperationCoordinator, CredentialOperationCoordinator } from "./coordination.js";
import { createAuthPool, createAuthCoordinationPool } from "./database.js";
import { initializeAuthSchema } from "./schema-initialize.js";

const ownerUrl = process.env.THESISTRACE_AUTH_TEST_OWNER_DATABASE_URL;
if (!ownerUrl) throw new Error("isolated test database required");
const runtimeUrl = new URL(ownerUrl);
if (runtimeUrl.hostname !== "127.0.0.1" || runtimeUrl.username !== "thesistrace_owner" || runtimeUrl.password !== "owner-test-password") throw new Error("isolated test database required");
runtimeUrl.username = "auth_runtime"; runtimeUrl.password = "auth-test-password";
const owner = new Pool({connectionString: ownerUrl});
const pool = createAuthPool(runtimeUrl.toString());
const coordinationPool = createAuthCoordinationPool(runtimeUrl.toString());
const settings = authTestSettings({databaseUrl: runtimeUrl.toString()});
const coordinator = new CredentialOperationCoordinator({authSecret: settings.secret, coordination: new AuthOperationCoordinator(coordinationPool), pool});
const messages = new Map<string, string>();
let ip = 0;
const auth = createThesisTraceAuth(settings, pool, {
  ...createClosedAuthLifecycle(),
  isResearcherActive: async id => (await pool.query('SELECT active FROM auth."user" WHERE id=$1',[id])).rows[0]?.active === true,
  recordSession: coordinator.recordSession,

});
const delivery = new EmailCodeDelivery({auth, publicOrigin: settings.publicOrigin, coordinator, sendEmail: async email => {
  if (email.to === "delivery-failure@example.com") throw new Error("simulated mail failure");
  messages.set(email.to, email.text.match(/\b[0-9]{6}\b/)![0]);
}});
const limiter = new AuthEndpointRateLimiter({authSecret: settings.secret, pool, scope: "email-code"});
const unavailable = async (): Promise<never> => { throw new Error("unrelated endpoint"); };
const deps: AuthAppDependencies = {
  isOperator: async () => false,
  sendSignInCode: email => delivery.send(email, "sign-in"),
  consumeEmailCodeRateLimit: (email,headers) => limiter.consume(email,headers),
  acceptInvitation: unavailable, inspectInvitation: unavailable,
  consumeInvitationRateLimit: unavailable,
  consumeOperatorProofRateLimit: (key, headers) => limiter.consume(`proof:${key}`,headers), confirmOperatorProof: unavailable,
  consumeOperatorProof: unavailable, hasOperatorCapability: unavailable,
  issueOperatorInvitation: unavailable, reissueOperatorInvitation: unavailable,
  listOperatorInvitations: unavailable, listOperatorResearchers: unavailable,
  revokeOperatorResearcherSessions: unavailable, issueMcpAccessToken: unavailable,
  readiness: async()=>true, publicOrigin: settings.publicOrigin,
  getSession: input => auth.api.getSession(input),
  authHandler: request => coordinator.handleAuthRequest(request, req => auth.handler(req), headers => auth.api.getSession({headers})),
};
const app = createAuthApp(deps);
async function post(path: string, body: unknown) {
  return app.request(`${settings.publicOrigin}/api/auth/${path}`, {method: "POST", headers: {origin: settings.publicOrigin, "content-type": "application/json", "x-thesistrace-client-ip": `192.0.2.${++ip}`}, body: JSON.stringify(body)});
}
async function send(email: string) { const response = await post("email-otp/send-verification-otp",{email,type:"sign-in"}); expect(response.status).toBe(200); return messages.get(email.trim().toLowerCase())!; }
async function signIn(email: string, otp: string) { return post("sign-in/email-otp", {email,otp}); }
async function users(email: string) { return (await owner.query('SELECT * FROM auth."user" WHERE email=$1',[email])).rows; }

describe.sequential("Email OTP public access",()=>{
  beforeAll(async()=>{await initializeAuthSchema(owner);});
  afterAll(async()=>{await Promise.all([pool.end(), coordinationPool.end(), owner.end()]);});
  it("creates only after verification, then logs in the same canonical email",async()=>{
    const otp = await send(" OtpResearcher@Example.com ");
    expect(await users("otpresearcher@example.com")).toHaveLength(0);
    const stored = await owner.query('SELECT value FROM auth."verification" WHERE identifier=$1',["sign-in-otp-otpresearcher@example.com"]);
    expect(stored.rows[0].value).not.toContain(otp);
    const first = await signIn("OTPRESEARCHER@example.com",otp); expect(first.status).toBe(200);
    const payload = await first.json(); expect(payload.user.emailVerified).toBe(true);
    expect(first.headers.get("set-cookie")).toContain("HttpOnly");
    const second = await signIn(" otpresearcher@example.com ", await send("otpresearcher@example.com"));
    expect(second.status).toBe(200); expect((await second.json()).user.id).toBe(payload.user.id);
    expect(await users("otpresearcher@example.com")).toHaveLength(1);
    expect((await owner.query('SELECT * FROM auth."account" WHERE "userId"=$1',[payload.user.id])).rowCount).toBe(0);
    await expect(owner.query('INSERT INTO auth."user" (id,name,email,"emailVerified","createdAt","updatedAt",active) VALUES (gen_random_uuid(),\'duplicate\',\'otpresearcher@example.com\',true,now(),now(),true)')).rejects.toMatchObject({code:"23505"});
  });
  it("allows only one concurrent consumption and rejects replay",async()=>{
    const email="otp-parallel@example.com", otp=await send(email);
    const responses=await Promise.all([signIn(email,otp),signIn(email.toUpperCase(),otp)]);
    expect(responses.map(r=>r.status).sort()).toEqual([200,400]);
    expect((await signIn(email,otp)).status).toBe(400);
    expect(await users(email)).toHaveLength(1);
  });
  it("rejects expired codes and exhausted attempts",async()=>{
    const email="otp-expired@example.com", otp=await send(email);
    await owner.query('UPDATE auth."verification" SET "expiresAt"=now()-interval \'1 second\' WHERE identifier=$1',[`sign-in-otp-${email}`]);
    expect((await signIn(email,otp)).status).toBe(400);
    const fresh=await send(email); const wrong=fresh==="000000"?"111111":"000000";
    for(let n=0;n<3;n++) expect((await signIn(email,wrong)).status).toBe(400);
    expect((await signIn(email,fresh)).status).toBe(403);
    expect(await users(email)).toHaveLength(0);
  });
  it("does not establish sessions for deactivated accounts",async()=>{
    const email="otp-inactive@example.com"; expect((await signIn(email,await send(email))).status).toBe(200);
    await owner.query('UPDATE auth."user" SET active=false WHERE email=$1',[email]);
    expect((await signIn(email,await send(email))).status).toBe(403);
    expect(await users(email)).toHaveLength(1);
  });
  it("reports delivery failure and removes its undelivered code",async()=>{
    expect((await post("email-otp/send-verification-otp",{email:"delivery-failure@example.com",type:"sign-in"})).ok).toBe(false);
    expect((await owner.query('SELECT * FROM auth."verification" WHERE identifier=$1',["sign-in-otp-delivery-failure@example.com"])).rowCount).toBe(0);
  });
  it("rejects other OTP purposes, profile injection and password login",async()=>{
    expect((await post("email-otp/send-verification-otp",{email:"new@example.com",type:"email-verification"})).status).toBe(400);
    expect((await post("sign-in/email-otp",{email:"new@example.com",otp:"123456",active:true})).status).toBe(400);
    expect((await post("sign-in/email",{email:"new@example.com",password:"password-not-supported"})).status).toBe(404);
  });
  it("requires a separate one-time Operator code and retains exact-action proof binding", async () => {
    const email = "otp-operator@example.com";
    const login = await signIn(email, await send(email));
    const {user} = await login.json();
    const session = (await pool.query('SELECT id FROM auth."session" WHERE "userId"=$1',[user.id])).rows[0];
    const principal = {researcherId: user.id, sessionId: session.id};
    await new OperatorAssignmentService({pool}).assign({researcherId: user.id});
    const codes = new OperatorEmailCode({auth, pool, delivery, coordinator});
    const proofs = new OperatorProofService({pool, verifyCode: codes.verify});
    const request = {operation: "researcher.sessions.revoke" as const, researcherId: user.id};
    await expect(proofs.confirm(principal, {...request, otp: await send(email)})).rejects.toBeInstanceOf(OperatorCodeInvalidError);
    await codes.send(principal);
    const otp = messages.get(email)!;
    const results = await Promise.allSettled([proofs.confirm(principal, {...request,otp}), proofs.confirm(principal, {...request,otp})]);
    expect(results.filter(result=>result.status === "fulfilled")).toHaveLength(1);
    const success = results.find(result=>result.status === "fulfilled");
    if (success?.status !== "fulfilled") throw new Error("missing proof");
    const proof = success.value.proof;
    await expect(proofs.claim(principal, {...request, researcherId:"00000000-0000-4000-8000-000000000001",proof})).rejects.toBeInstanceOf(OperatorProofInvalidError);
    await expect(proofs.claim(principal, {...request,proof})).resolves.toHaveProperty("sessionId",session.id);
  });

  it("rate limits a canonical email across IPs and rejects cross-origin delivery", async () => {
    for (let n=0; n<5; n++) await send("otp-limited@example.com");
    const limited = await post("email-otp/send-verification-otp", {email:" OTP-LIMITED@EXAMPLE.COM ", type:"sign-in"});
    expect(limited.status).toBe(429); expect(Number(limited.headers.get("retry-after"))).toBeGreaterThan(0);
    const crossOrigin = await app.request(`${settings.publicOrigin}/api/auth/email-otp/send-verification-otp`, {method:"POST", headers:{origin:"https://attacker.example","content-type":"application/json"},body:JSON.stringify({email:"cross-origin@example.com",type:"sign-in"})});
    expect(crossOrigin.status).toBe(403); expect(messages.has("cross-origin@example.com")).toBe(false);
  });

});
