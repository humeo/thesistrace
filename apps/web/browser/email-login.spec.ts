import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { build } from "vite";
const styles = readFileSync(new URL("../src/styles.css", import.meta.url),"utf8");
let script: string;
test.beforeAll(async()=>{
  const result=await build({configFile:false,logLevel:"silent",esbuild:{jsx:"automatic"},define:{"process.env.NODE_ENV":JSON.stringify("production")},build:{write:false,minify:false,lib:{entry:fileURLToPath(new URL("./fixtures/email-login.tsx",import.meta.url)),formats:["iife"],name:"EmailLogin"}}});
  if("on" in result)throw new Error("one-off build required");
  const chunk=(Array.isArray(result)?result:[result]).flatMap(b=>b.output).find(o=>o.type==="chunk"&&o.isEntry);
  if(chunk?.type!=="chunk")throw new Error("entry missing"); script=chunk.code;
});
for(const width of [1200,390]) {
  test(`email-only signup and existing-account login at ${width}px`,async({page})=>{
    let authenticated=false,failSend=true;
    const submitted: unknown[]=[];
    const user={id:"00000000-0000-4000-8000-000000000001",email:"researcher@example.com",name:"researcher",active:true};
    await page.route("http://auth.fixture/**",async route=>{
      const path=new URL(route.request().url()).pathname;
      let body: unknown = {};
      if(path === "/quanttrace-logo.png") { await route.fulfill({contentType:"image/png",body:readFileSync(new URL("../public/quanttrace-logo.png",import.meta.url))}); return; }
      if(path==="/login") {await route.fulfill({contentType:"text/html",body:`<style>${styles}</style><div id="root"></div>`});return;}
      if(path==="/api/auth/get-session")body=authenticated?{session:{id:"00000000-0000-4000-8000-000000000002"},user}:null;
      else if(path==="/api/auth/operator/capability") {await route.fulfill({status:404,body:""});return;}
      else if(path==="/api/auth/email-otp/send-verification-otp") {
        submitted.push(route.request().postDataJSON());
        if(failSend){failSend=false;await route.fulfill({status:503,contentType:"application/json",body:JSON.stringify({code:"AUTH_SERVICE_UNAVAILABLE"})});return;}
        body={success:true};
      } else if(path==="/api/auth/sign-in/email-otp") {
        const payload=route.request().postDataJSON();submitted.push(payload);
        if(payload.otp!=="123456") {await route.fulfill({status:400,contentType:"application/json",body:JSON.stringify({code:"INVALID_OTP"})});return;}
        authenticated=true;body={user,token:"test-session"};
      } else if(path==="/api/researcher/bootstrap")body={researcher_id:user.id,system_folders:{default:"folder_default",batch_research:"folder_batch_research"}};
      else throw new Error(`unexpected request ${path}`);
      await route.fulfill({contentType:"application/json",body:JSON.stringify(body)});
    });
    await page.setViewportSize({width,height:850});
    await page.goto("http://auth.fixture/login?returnTo=%2Fresearch");await page.addScriptTag({content:script});
    await expect(page.getByRole("heading",{name:"Get started with QuantTrace"})).toBeVisible();
    await expect(page.locator('input[type="password"]')).toHaveCount(0);
    await page.getByLabel("Email",{exact:true}).fill("Researcher@Example.com");
    await page.getByRole("button",{name:"Continue with email"}).click();
    await expect(page.getByRole("alert")).toContainText("could not be sent");
    await expect(page.getByLabel("Email",{exact:true})).toBeVisible();
    await page.getByRole("button",{name:"Continue with email"}).click();
    await expect(page.getByLabel("Verification code")).toBeFocused();
    await page.screenshot({path:test.info().outputPath(`email-code-${width}.png`)});
    await expect(page.getByRole("button",{name:/Resend code in/})).toBeDisabled();
    await page.getByLabel("Verification code").fill("000000");
    await page.getByRole("button",{name:"Verify and continue"}).click();
    await expect(page.getByRole("alert")).toContainText("incorrect or has expired");
    await page.getByLabel("Verification code").fill("123456");
    await page.getByRole("button",{name:"Verify and continue"}).click();
    await expect(page.getByRole("status")).toHaveText("Signed in as researcher@example.com");
    expect(submitted).toContainEqual({email:"researcher@example.com",type:"sign-in"});
    expect(submitted).toContainEqual(expect.objectContaining({email:"researcher@example.com",otp:"123456"}));
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  });
}
