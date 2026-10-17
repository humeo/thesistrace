import { describe, expect, it } from "vitest";
import { createTurnstileVerifier, TURNSTILE_VERIFY_URL } from "./turnstile.js";
const settings={secretKey:"secret-canary", publicOrigin:"https://qagentis.com",verifyUrl:TURNSTILE_VERIFY_URL};
describe("Turnstile Siteverify form binding",()=>{
  it("uses the official API and validates the hostname and action",async()=>{
    const verifier=createTurnstileVerifier(settings, async(input,init)=>{
      expect(input).toBe(TURNSTILE_VERIFY_URL);
      expect(new URLSearchParams(init!.body as URLSearchParams).get("secret")).toBe("secret-canary");
      expect(new URLSearchParams(init!.body as URLSearchParams).get("remoteip")).toBe("192.0.2.1");
      expect(init!.redirect).toBe("error");
      return Response.json({success:true,hostname:"qagentis.com",action:"sign-in-code"});
    });
    expect(await verifier("token", "192.0.2.1")).toBe(true);
  });
  it.each([{success:false,"error-codes":["timeout-or-duplicate"]},{success:true,hostname:"attacker.com",action:"sign-in-code"},{success:true,hostname:"qagentis.com",action:"other"},{success:true}])("rejects invalid, expired, replayed or mismatched challenges: %j",async body=>{
    expect(await createTurnstileVerifier(settings,async()=>Response.json(body))("token","192.0.2.1")).toBe(false);
  });
  it("rejects an empty or oversized response before reaching the provider",async()=>{
    const verifier=createTurnstileVerifier(settings,async()=>{throw new Error("must not reach provider");});
    expect(await verifier("", "192.0.2.1")).toBe(false);
    expect(await verifier("x".repeat(2049), "192.0.2.1")).toBe(false);
  });
  it.each([new Response(null,{status:503}),Response.json({not:"siteverify"})])("fails closed when the provider is unavailable or malformed",async response=>{
    await expect(createTurnstileVerifier(settings,async()=>response)("token","192.0.2.1")).rejects.toThrow();
  });
});
