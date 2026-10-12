import { serveTurnstile } from "../../../tests/fixtures/turnstile";
import { fontStylesheet, serveBrandAssets } from "./brand-assets";
import { buildProductFixture } from "./build-product-fixture";
import { expect, test } from "@playwright/test";
let styles: string;
let script: string;
test.beforeAll(async()=>{
  ({ script, styles } = await buildProductFixture(new URL("./fixtures/email-login.tsx", import.meta.url), "EmailLogin"));
});
test.beforeEach(async ({page}) => {await serveTurnstile(page);});
for(const width of [1200]) {
  test(`email-only signup and existing-account login at ${width}px`,async({page})=>{
    let authenticated=false,failSend=true;
    const submitted: unknown[]=[];
    const user={id:"00000000-0000-4000-8000-000000000001",email:"researcher@example.com",name:"researcher",active:true};
    await page.route("http://auth.fixture/**",async route=>{
      const path=new URL(route.request().url()).pathname;
      let body: unknown = {};
      if(path==="/login") {await route.fulfill({contentType:"text/html",body:`${fontStylesheet}<style>${styles}</style><div id="root"></div>`});return;}
      if(path==="/api/auth/get-session")body=authenticated?{session:{id:"00000000-0000-4000-8000-000000000002"},user}:null;
      else if(path==="/api/auth/operator/capability") {await route.fulfill({status:404,body:""});return;}
      else if(path==="/api/auth/email-otp/challenge") body={siteKey:"1x00000000000000000000AA",action:"sign-in-code"};
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
    await serveBrandAssets(page);
    await page.setViewportSize({width,height:850});
    await page.goto("http://auth.fixture/login?returnTo=%2Fresearch");await page.addScriptTag({content:script});
    await expect(page.getByRole("heading",{name:"Welcome to QAgentis"})).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({path:test.info().outputPath(`email-login-${width}.png`)});
    await expect(page.locator('input[type="password"]')).toHaveCount(0);
    await page.getByLabel("Email",{exact:true}).fill("Researcher@Example.com");
    await page.getByRole("button",{name:"Continue with email"}).click();
    await expect(page.getByRole("alert")).toContainText("temporarily unavailable");
    await expect(page.getByLabel("Email",{exact:true})).toBeVisible();
    await page.getByRole("button",{name:"Continue with email"}).click();
    await expect(page.getByRole("textbox", {name: "Verification code", exact: true})).toBeFocused();
    const codeInputs = page.getByRole("textbox");
    await expect(codeInputs).toHaveCount(6);
    await expect(codeInputs.first()).toHaveAttribute("autocomplete", "one-time-code");
    await page.screenshot({path:test.info().outputPath(`email-code-${width}.png`)});
    await expect(page.getByRole("button",{name:/Resend code in/})).toBeDisabled();
    await expect(page.getByRole("button",{name:"Verify and continue"})).toBeDisabled();
    await codeInputs.first().press("1");
    await expect(codeInputs.nth(1)).toBeFocused();
    await codeInputs.nth(1).press("a");
    await expect(codeInputs.nth(1)).toHaveValue("");
    await codeInputs.nth(1).press("2");
    await expect(codeInputs.nth(2)).toBeFocused();
    await codeInputs.nth(2).press("Backspace");
    await expect(codeInputs.nth(1)).toBeFocused();
    await expect(codeInputs.nth(1)).toHaveValue("");
    await expect(codeInputs.first()).toHaveValue("1");
    await page.getByRole("button",{name:"Edit",exact:true}).click();
    await expect(page.getByLabel("Email",{exact:true})).toBeFocused();
    await expect(page.getByLabel("Email",{exact:true})).toHaveValue("researcher@example.com");
    await expect(page.getByRole("button",{name:"Continue with email"})).toBeDisabled();
    await page.clock.install();
    await page.clock.fastForward(61_000);
    await page.getByRole("button",{name:"Continue with email"}).click();
    await expect(page.getByRole("textbox", {name: "Verification code", exact: true})).toBeFocused();
    for (const input of await codeInputs.all()) await expect(input).toHaveValue("");
    await page.getByRole("textbox", {name: "Verification code", exact: true}).fill("000000");
    await page.getByRole("button",{name:"Verify and continue"}).click();
    await expect(page.getByRole("alert")).toContainText("incorrect or has expired");
    for (const input of await codeInputs.all()) await expect(input).toHaveAttribute("aria-invalid", "true");
    await codeInputs.first().evaluate(input => {
      const clipboardData = new DataTransfer();
      clipboardData.setData("text/plain", "123 456");
      input.dispatchEvent(new ClipboardEvent("paste", {bubbles: true, clipboardData}));
    });
    await expect(page.getByRole("alert")).toHaveCount(0);
    for (const [index, digit] of [..."123456"].entries()) await expect(codeInputs.nth(index)).toHaveValue(digit);
    await expect(codeInputs.nth(5)).toBeFocused();
    await page.getByRole("button",{name:"Verify and continue"}).click();
    await expect(page.getByRole("status")).toHaveText("Signed in as researcher@example.com");
    expect(submitted).toContainEqual(expect.objectContaining({email:"researcher@example.com",type:"sign-in",captcha_token:expect.stringContaining("test-turnstile:")}));
    expect(submitted).toContainEqual(expect.objectContaining({email:"researcher@example.com",otp:"123456"}));
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  });
}

test("authentication recovery deadline preserves the code and enables manual retry on desktop", async ({page}) => {
  let authenticated = false;
  let limited = true;
  const user = {id: "00000000-0000-4000-8000-000000000001", email: "researcher@example.com", name: "researcher", active: true};
  await page.route("http://auth.fixture/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/login") {await route.fulfill({contentType: "text/html", body: `${fontStylesheet}<style>${styles}</style><div id="root"></div>`}); return;}
    if (path === "/api/auth/operator/capability") {await route.fulfill({status: 404, body: ""}); return;}
    if (path === "/api/auth/sign-in/email-otp" && limited) {
      limited = false;
      await route.fulfill({status: 429, headers: {"Retry-After": "23"}, contentType: "application/json", body: JSON.stringify({message: "Too many requests"})});
      return;
    }
    let body: unknown;
    if (path === "/api/auth/get-session") body = authenticated ? {user} : null;
    else if (path === "/api/auth/email-otp/challenge") body={siteKey:"1x00000000000000000000AA",action:"sign-in-code"};
    else if (path === "/api/auth/email-otp/send-verification-otp") body = {success: true};
    else if (path === "/api/auth/sign-in/email-otp") {authenticated = true; body = {user};}
    else if (path === "/api/researcher/bootstrap") body = {researcher_id: user.id, system_folders: {default: "folder_default", batch_research: "folder_batch_research"}};
    else throw new Error("Unexpected request " + path);
    await route.fulfill({contentType: "application/json", body: JSON.stringify(body)});
  });
  await serveBrandAssets(page);
  await page.setViewportSize({width: 1200, height: 850});
  await page.goto("http://auth.fixture/login"); await page.addScriptTag({content: script});
  await page.clock.install();
  await page.getByLabel("Email", {exact: true}).fill(user.email);
  await page.getByRole("button", {name: "Continue with email"}).click();
  await page.getByRole("textbox", {name: "Verification code", exact: true}).fill("123456");
  await page.getByRole("button", {name: "Verify and continue"}).click();
  await expect(page.getByRole("alert")).toContainText("23s");
  await expect(page.getByRole("button", {name: "Verify and continue"})).toBeDisabled();
  await page.clock.fastForward(24_000);
  await expect(page.getByRole("button", {name: "Verify and continue"})).toBeEnabled();
  for (const [index, digit] of [..."123456"].entries()) await expect(page.getByRole("textbox").nth(index)).toHaveValue(digit);
  await expect(page.getByRole("status")).toHaveCount(0);
  await page.getByRole("button", {name: "Verify and continue"}).click();
  await expect(page.getByRole("status")).toHaveText("Signed in as researcher@example.com");
});
