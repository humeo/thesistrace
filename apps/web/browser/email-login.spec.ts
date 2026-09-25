import { fontStylesheet, serveBrandAssets } from "./brand-assets";
import { buildProductFixture } from "./build-product-fixture";
import { expect, test } from "@playwright/test";
let styles: string;
let script: string;
test.beforeAll(async()=>{
  ({ script, styles } = await buildProductFixture(new URL("./fixtures/email-login.tsx", import.meta.url), "EmailLogin"));
});
for(const width of [1200,390,320]) {
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
    await expect(page.getByRole("heading",{name:"Welcome to Quantgrove"})).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({path:test.info().outputPath(`email-login-${width}.png`)});
    await expect(page.locator('input[type="password"]')).toHaveCount(0);
    await page.getByLabel("Email",{exact:true}).fill("Researcher@Example.com");
    await page.getByRole("button",{name:"Continue with email"}).click();
    await expect(page.getByRole("alert")).toContainText("could not be sent");
    await expect(page.getByLabel("Email",{exact:true})).toBeVisible();
    await page.getByRole("button",{name:"Continue with email"}).click();
    await expect(page.getByLabel("Verification code")).toBeFocused();
    await page.screenshot({path:test.info().outputPath(`email-code-${width}.png`)});
    if (width < 768) {
      const editHeight = await page.getByRole("button",{name:"Edit",exact:true}).evaluate(button => button.getBoundingClientRect().height);
      expect(editHeight).toBeGreaterThanOrEqual(44);
    }
    await expect(page.getByRole("button",{name:/Resend code in/})).toBeDisabled();
    await expect(page.getByRole("button",{name:"Verify and continue"})).toBeDisabled();
    await page.getByRole("button",{name:"Edit",exact:true}).click();
    await expect(page.getByLabel("Email",{exact:true})).toBeFocused();
    await expect(page.getByLabel("Email",{exact:true})).toHaveValue("researcher@example.com");
    await page.getByRole("button",{name:"Continue with email"}).click();
    await expect(page.getByLabel("Verification code")).toBeFocused();
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

test("invitation mismatch, failed acceptance and retry preserve entered values", async ({page}) => {
  let authenticated = false;
  let failAccept = true;
  const user = {id:"00000000-0000-4000-8000-000000000003",email:"invited@example.com",name:"invited",active:true};
  await page.route("http://auth.fixture/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/accept-invitation") {
      await route.fulfill({contentType:"text/html",body:`${fontStylesheet}<style>${styles}</style><div id="root"></div>`});
      return;
    }
    if (path === "/api/auth/get-session") {
      await route.fulfill({contentType:"application/json",body:JSON.stringify(authenticated ? {session:{id:"00000000-0000-4000-8000-000000000004"},user} : null)});
      return;
    }
    if (path === "/api/auth/researcher-invitation/inspect") {
      await route.fulfill({contentType:"application/json",body:JSON.stringify({email:user.email})});
      return;
    }
    if (path === "/api/auth/researcher-invitation/accept") {
      const payload = route.request().postDataJSON();
      expect(payload).toEqual({password:"Secure-password-123",token:"fixture-token"});
      if (failAccept) {
        failAccept = false;
        await route.fulfill({status:503,contentType:"application/json",body:JSON.stringify({code:"AUTH_SERVICE_UNAVAILABLE"})});
        return;
      }
      authenticated = true;
      await route.fulfill({contentType:"application/json",body:"{}"});
      return;
    }
    if (path === "/api/researcher/bootstrap") {
      await route.fulfill({contentType:"application/json",body:JSON.stringify({researcher_id:user.id,system_folders:{default:"folder_default",batch_research:"folder_batch_research"}})});
      return;
    }
    if (path === "/api/auth/operator/capability") {
      await route.fulfill({status:404,body:""});
      return;
    }
    throw new Error(`unexpected request ${path}`);
  });
  await serveBrandAssets(page);
  await page.setViewportSize({width:390,height:850});
  await page.goto("http://auth.fixture/accept-invitation");
  await page.addScriptTag({content:script});
  await expect(page.getByRole("heading",{name:"Create your Quantgrove access"})).toBeVisible();
  await expect(page.getByLabel("Email",{exact:true})).toHaveValue(user.email);
  const password = page.getByLabel("Password",{exact:true});
  const confirmation = page.getByLabel("Confirm password",{exact:true});
  await password.fill("Secure-password-123");
  await confirmation.fill("Different-password-123");
  await page.getByRole("button",{name:"Accept invitation"}).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await confirmation.fill("Secure-password-123");
  await page.getByRole("button",{name:"Accept invitation"}).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(password).toHaveValue("Secure-password-123");
  await expect(confirmation).toHaveValue("Secure-password-123");
  await page.getByRole("button",{name:"Accept invitation"}).click();
  await expect(page.getByRole("status")).toHaveText("Signed in as invited@example.com");
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
