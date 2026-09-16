import {TestRun} from '../../tooling/test/resources.mjs';
import {finish} from '../../tooling/test/cleanup.mjs';
const run=new TestRun('integration');let status=0;
try{
await run.allocate();run.compose_cleanup_required=true;
await run.phase('target-infrastructure',()=>run.compose(['up','--detach','--wait','--wait-timeout','300','postgres','rustfs','resend-fake']));
await run.updatePorts('rustfs');await run.waitForS3();
await run.compose(['up','--detach','auth-initialize']);await run.compose(['wait','auth-initialize']);
await run.compose(['up','--detach','--wait','--wait-timeout','120','auth']);
await run.updatePorts('postgres','rustfs','auth','resend-fake');run.auth_internal_origin=`http://127.0.0.1:${run.auth_port}`;run.resend_test_origin=`http://127.0.0.1:${run.resend_port}`;
await run.host(['uv','run','thesistrace-initialize']);
await run.phase('rank-ic-tests',()=>run.host(['uv','run','pytest','-c',`${run.repo_root}/apps/core/pyproject.toml`,'--rootdir',run.repo_root,'-q','apps/core/tests/integration/test_research_run_ownership.py::test_strategy_metric_sorting_precedes_pagination','apps/core/tests/acceptance/test_core_current_head_research_run_execution.py::test_research_kinds_publish_identical_factor_evidence_when_strategy_changes',`--junitxml=${run.pytest_report}`]));
}catch(e){console.error(e.message);status=e.status||1}finally{process.exitCode=await finish(run,status)}
