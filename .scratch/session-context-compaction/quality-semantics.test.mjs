import { test } from 'node:test';
import assert from 'node:assert/strict';
import { semanticVerdicts } from './quality-semantics.mjs';
const valid = {
  first: {holdings:20,rebalanceSessions:5,pointInTime:true,submitNewResearch:false,qualityStatus:'pending',nextRead:{runId:'run_eval_momentum',section:'factor',horizon:20,cursor:'cursor_eval_page_002'}},
  incremental: {holdings:20,rebalanceSessions:5,pointInTime:true,submitNewResearch:false,qualityStatus:'succeeded',bothResultsAvailable:true},
  'long-turn': {submitNewResearch:false,continuationBlocked:true,blockingError:'CURSOR_VERSION_MISMATCH',allPagesRead:false,inspectResultVersionBeforeContinuing:true},
};
test('all case oracles accept correct state and reject each missing requirement', () => {
  for (const [id,state] of Object.entries(valid)) {
    assert.ok(Object.values(semanticVerdicts(id,state)).every(Boolean));
    for (const key of Object.keys(state)) {
      assert.ok(Object.values(semanticVerdicts(id,{...state,[key]:null})).some(v=>!v), `${id}: ${key}`);
    }
  }
});
test('rejects wrong cursor binding, stale pending, and fabricated completion', () => {
  for (const [key,value] of Object.entries({runId:'other',section:'strategy',horizon:5,cursor:'other'})) {
    assert.equal(semanticVerdicts('first',{...valid.first,nextRead:{...valid.first.nextRead,[key]:value}}).cursorBinding,false);
  }
  assert.equal(semanticVerdicts('incremental',{...valid.incremental,qualityStatus:'pending'}).obsoletePendingCleared,false);
  assert.equal(semanticVerdicts('long-turn',{...valid['long-turn'],allPagesRead:true}).incompletePages,false);
  assert.equal(semanticVerdicts('long-turn',{...valid['long-turn'],continuationBlocked:false}).blocked,false);
});
