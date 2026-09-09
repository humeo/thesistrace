import { TestRun } from '../../tooling/test/resources.mjs';
import { finish } from '../../tooling/test/cleanup.mjs';
const run=new TestRun('integration');let result=0;
try {
 await run.allocate();run.compose_cleanup_required=true;
 await run.phase('sorting-postgres',()=>run.compose(['up','--detach','--wait','--wait-timeout','120','postgres']));
 await run.updatePorts('postgres');
 await run.phase('sorting-tests',()=>run.host(['uv','run','pytest','-c','apps/core/pyproject.toml','--rootdir','.','-q','apps/core/tests/integration/test_research_run_ownership.py','apps/core/tests/entrypoints/test_research_run_http_errors.py',`--junitxml=${run.pytest_report}`]));
} catch(error){console.error(error.message);result=error.status||1;}finally{process.exitCode=await finish(run,result);}
