import { Pool } from "pg";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { createAuthPool } from "./database.js";
import { initializeAuthSchema } from "./schema-initialize.js";
import { SignInCodeAdmission } from "./sign-in-code-admission.js";

const ownerUrl = process.env.THESISTRACE_AUTH_TEST_OWNER_DATABASE_URL;
if (!ownerUrl) throw new Error("isolated database required");
const runtimeUrl = new URL(ownerUrl);
if (runtimeUrl.hostname !== "127.0.0.1" || runtimeUrl.password !== "owner-test-password") throw new Error("isolated database required");
runtimeUrl.username = "auth_runtime"; runtimeUrl.password = "auth-test-password";
const owner = new Pool({connectionString: ownerUrl});
const pool = createAuthPool(runtimeUrl.toString());
let now = 1800000000000;
let ip = 0;
const headers = (address = "192.0.2." + ++ip) => new Headers({"x-thesistrace-client-ip": address});
const settings = {pool, authSecret: "0123456789abcdef0123456789abcdef", globalHourlyLimit:25, globalDailyLimit:100, clock:()=>new Date(now), verifyChallenge:async (token:string)=>token === "valid"};
const create = (overrides: Partial<ConstructorParameters<typeof SignInCodeAdmission>[0]> = {}) => new SignInCodeAdmission({...settings,...overrides});
const allow = {allowed: true};

describe.sequential("Sign-in mail admission with persisted PostgreSQL budgets",()=>{
  beforeAll(async()=>{await initializeAuthSchema(owner);});
  beforeEach(async()=>{await owner.query('TRUNCATE auth."rateLimit"'); now=1800000000000; ip=0;});
  afterAll(async()=>{await pool.end(); await owner.end();});
  it("admits only one simultaneous send across instances and IPs for a canonical email",async()=>{
    const instances=[create(),create()];
    const results=await Promise.all(Array.from({length:10},(_,i)=>instances[i%2]!.admit(i%2?" USER@EXAMPLE.COM ":"user@example.com","valid",headers())));
    expect(results.filter(r=>r.allowed)).toHaveLength(1);
    expect(results.filter(r=>!r.allowed)).toEqual(Array(9).fill({allowed:false,reason:"rate-limit",retryAfterSeconds:60}));
    const keys=await owner.query('SELECT key FROM auth."rateLimit"');
    expect(JSON.stringify(keys.rows)).not.toContain("user@example.com");
    expect(JSON.stringify(keys.rows)).not.toContain("192.0.2.");
  });
  it("rejected requests do not extend cooldown or consume hourly capacity",async()=>{
    const limiter=create();
    expect(await limiter.admit("user@example.com","valid",headers())).toEqual(allow);
    for (let i=0;i<4;i++) {now+=10000; expect(await limiter.admit("user@example.com","valid",headers())).toMatchObject({allowed:false});}
    now+=20000;
    expect(await limiter.admit("user@example.com","valid",headers())).toEqual(allow);
    for(let i=0;i<3;i++){now+=60000;expect(await limiter.admit("user@example.com","valid",headers())).toEqual(allow);}
    now+=60000;
    expect(await limiter.admit("user@example.com","valid",headers())).toEqual({allowed:false,reason:"rate-limit",retryAfterSeconds:3300});
    now+=3300000;
    expect(await create().admit("user@example.com","valid",headers())).toEqual(allow);
  });
  it("persists the daily mailbox cap across hourly resets and process restarts",async()=>{
    for(let hour=0;hour<2;hour++){
      for(let i=0;i<5;i++){expect(await create().admit("daily@example.com","valid",headers())).toEqual(allow);now+=60000;}
      now=1800000000000+(hour+1)*3600000;
    }
    expect(await create().admit("daily@example.com","valid",headers())).toEqual({allowed:false,reason:"rate-limit",retryAfterSeconds:79200});
    now=1800000000000+86400000;
    expect(await create().admit("daily@example.com","valid",headers())).toEqual(allow);
  });
  it("atomically caps distributed multi-mailbox sends and records one budget alert per window",async()=>{
    const reached: unknown[]=[];
    const limiter=create({globalHourlyLimit:3,globalDailyLimit:5,onBudgetReached:(windowSeconds,limit)=>reached.push({windowSeconds,limit})});
    const results=await Promise.all(Array.from({length:8},(_,i)=>limiter.admit("mail"+i+"@example.com","valid",headers())));
    expect(results.filter(r=>r.allowed)).toHaveLength(3);
    expect(results.filter(r=>!r.allowed)).toEqual(Array(5).fill({allowed:false,reason:"rate-limit",retryAfterSeconds:3600}));
    expect(reached).toEqual([{windowSeconds:3600,limit:3}]);
    now+=3600000;
    for(let i=8;i<10;i++) expect(await limiter.admit("mail"+i+"@example.com","valid",headers())).toEqual(allow);
    expect(await limiter.admit("next@example.com","valid",headers())).toEqual({allowed:false,reason:"rate-limit",retryAfterSeconds:82800});
    expect(reached).toEqual([{windowSeconds:3600,limit:3},{windowSeconds:86400,limit:5}]);
    now+=82800000;
    expect(await limiter.admit("next@example.com","valid",headers())).toEqual(allow);
  });
  it("verification failures and outages consume no mailbox or mail budget",async()=>{
    const limiter=create({globalHourlyLimit:1,globalDailyLimit:1});
    expect(await limiter.admit("victim@example.com","invalid",headers())).toEqual({allowed:false,reason:"challenge",retryAfterSeconds:0});
    expect(await create({verifyChallenge:async()=>{throw new Error("outage");}}).admit("victim@example.com","valid",headers())).toEqual({allowed:false,reason:"unavailable",retryAfterSeconds:0});
    expect(await limiter.admit("victim@example.com","valid",headers())).toEqual(allow);
  });
  it.each([
    ["2001:db8:1:2::1","2001:DB8:0001:0002::abcd"],
    ["192.0.2.1","::ffff:c000:201"],
  ])("shares the IP request budget for %s and %s before verifying a challenge",async(first,second)=>{
    const limiter=create({verifyChallenge:async()=>false});
    for(let i=0;i<5;i++) expect(await limiter.admit("victim@example.com","invalid",headers(first))).toMatchObject({reason:"challenge"});
    expect(await limiter.admit("different@example.com","valid",headers(second))).toEqual({allowed:false,reason:"rate-limit",retryAfterSeconds:60});
    now+=60000;
    expect(await limiter.admit("different@example.com","invalid",headers(second))).toMatchObject({reason:"challenge"});
  });
  it("rejects missing or malformed gateway identity rather than trusting other forwarded headers",async()=>{
    for(const h of [new Headers({"x-forwarded-for":"192.0.2.1"}),headers("192.0.2.1, 192.0.2.2"),headers("garbage")]) expect(await create().admit("user@example.com","valid",h)).toMatchObject({allowed:false,reason:"unavailable"});
  });
});
