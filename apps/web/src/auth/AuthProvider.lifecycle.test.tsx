// @vitest-environment happy-dom
import { act } from 'react';
import {createRoot} from 'react-dom/client';
import {afterEach,expect,test,vi} from 'vitest';
import {AuthProvider,useAuth} from './AuthProvider';
import {coreFetch} from './coreFetch';
const {getSession,signOut,emailOtp}=vi.hoisted(()=>({getSession:vi.fn(),signOut:vi.fn(),emailOtp:vi.fn()}));
vi.mock('./client',()=>({authClient:{getSession,signOut,signIn:{emailOtp}}}));
(globalThis as typeof globalThis & {IS_REACT_ACT_ENVIRONMENT:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
const researcherId='b9aaeb26-fb97-4d1a-af62-a29c73021caa';
test.each(['sign-out','core-401'])('ignores delayed bootstrap after %s',async action=>{
  getSession.mockResolvedValue({data:{user:{active:true,id:researcherId,email:'audit@example.com',name:'Audit'}},error:null});
  signOut.mockResolvedValue({data:null,error:null});
  let completeBootstrap!:(response:Response)=>void;
  const pendingBootstrap=new Promise<Response>(resolve=>{completeBootstrap=resolve});
  vi.stubGlobal('fetch',async(input:RequestInfo|URL)=>{
    const path=String(input);
    if(path==='/api/auth/operator/capability') return new Response(null,{status:404});
    if(path==='/api/researcher/bootstrap') return pendingBootstrap;
    if(path==='/api/design-audit-401') return new Response(null,{status:401});
    throw new Error('Unexpected request '+path);
  });
  let auth!:ReturnType<typeof useAuth>;
  function Consumer(){auth=useAuth();return null;}
  const container=document.createElement('div');
  const root=createRoot(container);
  try {
    await act(async()=>root.render(<AuthProvider><Consumer/></AuthProvider>));
    expect(auth.state.status).toBe('setup');
    await act(async()=>{
      if(action==='sign-out') await auth.signOut();
      else await coreFetch('/api/design-audit-401').catch(()=>undefined);
    });
    expect(auth.state.status).toBe('anonymous');
    await act(async()=>completeBootstrap(Response.json({researcher_id:researcherId,system_folders:{default:'folder_default',batch_research:'folder_batch_research'}})));
    expect(auth.state.status).toBe('anonymous');
  } finally {await act(async()=>root.unmount());}
});


test.each([200, 401, 503])("ignores old identity bootstrap status %s after a new sign-in", async oldStatus => {
  const secondId = "b9aaeb26-fb97-4d1a-af62-a29c73021cab";
  const session = (id: string) => ({data: {user: {active: true, id, email: "audit@example.com", name: "Audit"}}, error: null});
  getSession.mockResolvedValue(session(researcherId));
  emailOtp.mockResolvedValue({data: {}, error: null});
  let finishOld!: (response: Response) => void;
  const pending = new Promise<Response>(resolve => { finishOld = resolve; });
  let first = true;
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    if (String(input) === "/api/auth/operator/capability") return new Response(null, {status: 404});
    if (String(input) === "/api/researcher/bootstrap") {
      if (first) {first = false; return pending;}
      return Response.json({researcher_id: secondId, system_folders: {default: "folder_default", batch_research: "folder_batch_research"}});
    }
    throw new Error("Unexpected request");
  });
  let auth!: ReturnType<typeof useAuth>;
  function Consumer(){auth = useAuth(); return null;}
  const root = createRoot(document.createElement("div"));
  try {
    await act(async () => root.render(<AuthProvider><Consumer /></AuthProvider>));
    expect(auth.state.status).toBe("setup");
    getSession.mockResolvedValue(session(secondId));
    await act(async () => {await auth.signIn("audit@example.com", "123456");});
    expect(auth.state).toMatchObject({status: "authenticated", session: {researcherId: secondId}});
    await act(async () => finishOld(oldStatus === 200 ? Response.json({researcher_id: researcherId, system_folders: {default: "folder_default", batch_research: "folder_batch_research"}}) : new Response(null, {status: oldStatus})));
    expect(auth.state).toMatchObject({status: "authenticated", session: {researcherId: secondId}});
  } finally {await act(async () => root.unmount());}
});

test.each(["session", "capability"])("ignores an old %s response after logout", async stage => {
  let finish!: (value: unknown) => void;
  const pending = new Promise(resolve => {finish = resolve;});
  const session = {data: {user: {active: true, id: researcherId, email: "audit@example.com", name: "Audit"}}, error: null};
  getSession.mockImplementation(async () => stage === "session" ? pending : session);
  signOut.mockResolvedValue({data: null, error: null});
  vi.stubGlobal("fetch", async () => await pending as Response);
  let auth!: ReturnType<typeof useAuth>;
  function Consumer(){auth = useAuth(); return null;}
  const root = createRoot(document.createElement("div"));
  try {
    await act(async () => root.render(<AuthProvider><Consumer /></AuthProvider>));
    await act(async () => {await auth.signOut();});
    await act(async () => finish(stage === "session" ? session : new Response(null, {status: 404})));
    expect(auth.state).toEqual({status: "anonymous", session: null});
  } finally {await act(async () => root.unmount());}
});


test("preserves identity during session throttling and recovers only after the deadline", async () => {
  let now = 1_000_000;
  vi.spyOn(Date, "now").mockImplementation(() => now);
  const session = {
    data: {user: {active: true, id: researcherId, email: "audit@example.com", name: "Audit"}},
    error: null,
  };
  getSession.mockResolvedValue(session);
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    if (String(input) === "/api/auth/operator/capability") return new Response(null, {status: 404});
    if (String(input) === "/api/researcher/bootstrap") return Response.json({
      researcher_id: researcherId,
      system_folders: {default: "folder_default", batch_research: "folder_batch_research"},
    });
    throw new Error("Unexpected request");
  });
  let auth!: ReturnType<typeof useAuth>;
  function Consumer() {auth = useAuth(); return null;}
  const root = createRoot(document.createElement("div"));
  try {
    await act(async () => root.render(<AuthProvider><Consumer /></AuthProvider>));
    expect(auth.state).toMatchObject({status: "authenticated", session: {researcherId}});
    getSession.mockImplementation(async ({fetchOptions}) => {
      await fetchOptions.onError({response: new Response(null, {status: 429, headers: {"Retry-After": "23"}})});
      return {data: null, error: {status: 429}};
    });
    await act(async () => {await auth.retry();});
    expect(auth.state).toMatchObject({status: "unavailable", session: {researcherId}, retryAt: now + 23_000});
    getSession.mockResolvedValue(session);
    now += 22_999;
    await act(async () => {await auth.retry();});
    expect(auth.state.status).toBe("unavailable");
    now += 1;
    await act(async () => {await auth.retry();});
    expect(auth.state).toMatchObject({status: "authenticated", session: {researcherId}});
    getSession.mockResolvedValue({data: null, error: {status: 401}});
    await act(async () => {await auth.retry();});
    expect(auth.state).toEqual({status: "anonymous", session: null});
  } finally {
    await act(async () => root.unmount());
  }
});
