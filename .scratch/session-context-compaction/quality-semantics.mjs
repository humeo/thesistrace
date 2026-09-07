// Independent case oracles. Never give these answers to the extraction model.
export const extractionInstruction = `Read the supplied session memory and summary only. Return one JSON object, without Markdown, representing the current task state. Use null for unknown values. Schema: {holdings:number|null,rebalanceSessions:number|null,pointInTime:boolean|null,qualityStatus:"pending"|"succeeded"|null,bothResultsAvailable:boolean|null,submitNewResearch:boolean|null,nextRead:{runId:string|null,section:string|null,horizon:number|null,cursor:string|null}|null,continuationBlocked:boolean|null,blockingError:string|null,allPagesRead:boolean|null,inspectResultVersionBeforeContinuing:boolean|null}. Resolve historical states using the latest decisions. Do not infer missing facts from outside the supplied context.`;

export function semanticVerdicts(caseId, value) {
  if (!value || typeof value !== 'object') return { validState: false };
  if (caseId === 'first') return {
    holdings: value.holdings === 20,
    rebalance: value.rebalanceSessions === 5,
    pointInTime: value.pointInTime === true,
    noResubmission: value.submitNewResearch === false,
    qualityPending: value.qualityStatus === 'pending',
    cursorBinding: value.nextRead?.runId === 'run_eval_momentum'
      && value.nextRead?.section === 'factor' && value.nextRead?.horizon === 20
      && value.nextRead?.cursor === 'cursor_eval_page_002',
  };
  if (caseId === 'incremental') return {
    holdings: value.holdings === 20,
    rebalance: value.rebalanceSessions === 5,
    pointInTime: value.pointInTime === true,
    noResubmission: value.submitNewResearch === false,
    obsoletePendingCleared: value.qualityStatus === 'succeeded',
    bothResultsAvailable: value.bothResultsAvailable === true,
  };
  if (caseId === 'long-turn') return {
    noResubmission: value.submitNewResearch === false,
    blocked: value.continuationBlocked === true,
    blockingError: value.blockingError === 'CURSOR_VERSION_MISMATCH',
    incompletePages: value.allPagesRead === false,
    inspectVersion: value.inspectResultVersionBeforeContinuing === true,
  };
  throw new Error('UNKNOWN_EVAL_CASE');
}
