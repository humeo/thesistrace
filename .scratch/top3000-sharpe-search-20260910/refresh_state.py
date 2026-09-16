"""Refresh research bookkeeping from saved responses, never claims a live poll."""
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ACTIVE = {"queued", "running", "cancelling"}

def records(folder):
    return [json.loads(path.read_text()) for path in (ROOT / folder).glob("*.json")]

def main():
    state = json.loads((ROOT / "SEARCH_STATE.json").read_text())
    submissions = records("submissions")
    accepted = [s for s in submissions if s.get("response", {}).get("outcome") == "accepted"]
    batch_ids = {s["response"]["batch_id"] for s in accepted if "batch_id" in s["response"]}
    single_ids = {s["response"]["run_id"] for s in accepted if "run_id" in s["response"]}
    batches = {r["id"]: r for r in records("batches")}
    runs = {r["id"]: r for r in records("runs")}
    results = records("results")
    strategy = [r for r in results if "summary" in r]
    small = [r for r in strategy if r["run"]["name"].startswith(("QS6 prescreen ","QS8 "))]
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    state["last_turn_classification"] = "progress"
    state["bookkeeping_source"] = "Saved live MCP responses; this local script does not poll remote jobs"
    state["submitted_tasks"] = {
        "factor_evaluations": sum(len(s["input"].get("factors", [])) + (s["input"].get("research_kind") == "factor_evaluation") for s in accepted),
        "strategy_backtests": sum(len(s["input"].get("strategies", [])) + (s["input"].get("research_kind") == "strategy_backtest") for s in accepted),
    }
    state["rejected_submission_requests"] = sum(s.get("response", {}).get("outcome") == "rejected" for s in submissions)
    factor_cases = set()
    for submission in accepted:
        inp = submission["input"]
        factors = inp.get("factors", []) if "batch_kind" in inp else ([inp] if inp.get("research_kind") == "factor_evaluation" else [])
        for factor in factors:
            factor_cases.add((factor["formula"], inp["start_date"], inp["end_date"], inp["universe"], inp["neutralization"]))
    state["unique_submitted_factor_cases"] = len(factor_cases)
    failed_ids = {i for i in single_ids if i in runs and runs[i]["status"] == "failed"}
    for batch_id in batch_ids:
        failed_ids.update(item["research_run_id"] for item in batches.get(batch_id, {}).get("items", []) if item["status"] == "failed")
    state["failed_run_attempts"] = sorted(failed_ids)
    state["collected"] = {
        "strategy_results": len(strategy),
        "all_result_records": len(results),
        "complete_nav_audits": len(list((ROOT / "observations").glob("*.json"))),
        "small_account_prescreen": len(small),
        "verified_100k_results": sum(float(r["summary"]["initial_cash_cny"]) == 100000 for r in strategy),
        "above_sharpe_1_2": [r["run"]["id"] for r in strategy if (r["summary"]["metrics"]["sharpe"] or 0) > 1.2],
    }
    latest_small = [r for r in strategy if r['run']['input']['start_date']=='2025-09-10'
                    and not r['run']['name'].startswith('QS16 1y common_valid_amount_cash ')
                    and r['run']['input']['holdings_count']<=20
                    and r['summary']['metrics']['maximum_drawdown']['value']<=0.2]
    if latest_small:
        best=max(latest_small,key=lambda r:r['summary']['metrics']['sharpe'])
        m=best['summary']['metrics']
        state['current_best_small_prescreen']={
            'run_id':best['run']['id'],'name':best['run']['name'],
            'actual_initial_cash_cny':float(best['summary']['initial_cash_cny']),
            'net_return':m['net_cumulative_return'],'maximum_drawdown':m['maximum_drawdown']['value'],
            'sharpe':m['sharpe'],'qualified_for_user':False,
            'rank_basis':'Highest native Sharpe among one-year runs with at most20 holdings and historical drawdown<=20%. Native capital differs from user; recent/phase and permissions remain unresolved.'}
    state['native_market_timing_report']='MARKET_TIMING.md'
    state['round11_plan']='round11-plan.json'
    state['round12_plan']='round12-plan.json'
    state['new_signal_rounds']={'plans':['round13-plan.json','round14-plan.json','round15-plan.json','round15-followup-plan.json'],
                                'primary_sources':'ROUND13_SOURCES.md','report':'NEW_SIGNALS.md'}
    state['market_score_switch']={'plans':['round16-plan.json','round16-followup-plan.json','round16-capital-quarter-plan.json'],
        'report':'MARKET_SWITCH.md','proof':'market-switch-proof.json',
        'exact_observation_duplicate_controls':['run_7297da0535ff4eacbb47','run_1b505fb2143246efb3e6'],
        'limitations':'H10R5 native3yMDD25.12% exceeds target. H20R10 native3ySharpe1.2085/MDD16.50%;100k extra10bp1ySharpe1.0548. H10R5 allboard100k1y/quarter pass,main_chinext quarter below1.2. No latest100k or3y100k proof.'}
    state['account_board_plan']='account-board-plan.json'
    state['switch_neighbors']={'plan':'round17-plan.json','report':'SWITCH_NEIGHBORS.md',
        'results':'switch-neighbor-comparison.json','new_native_cases':8,'joint_passing_neighbors':0,
        'limitation':'All4 predeclared neighbors fail joint1y/quarter Sharpe>1.2 and MDD<=20%; do not optimize additional intervals after observing results.'}
    state['regime_account_attribution']={'report':'REGIME_ACCOUNT_ATTRIBUTION.md','evidence':'regime-account-attribution.json',
        'model':'existing8 audited100k paths; target-state attribution, no new backtests or causal proof'}
    state['round18']={'plan':'round18-plan.json','sources':'ROUND17_SOURCES.md','report':'ROUND18_RESULTS.md',
        'quantile_diagnostic':'QUANTILE_COVERAGE.md','native_capital_cny':10000000,
        'note':'All6 factors collected. LowCV actual H10R20/H20R20 failed economic screen. Efficiency change passed fixed factor screen; two-item strategy batch admission rejected, exact-input single runs both terminal resource failures at4/242research sessions. No Result and no negative economic claim; do not repeat unchanged resource failures.'}
    state['round19']={'plan':'round19-plan.json','report':'ROUND19_RESULTS.md','execution_state':'round19-execution-state.json',
        'note':'Seven existing positive factors, fixedH10/H20R20, all14actualyear strategies now collected and all failed screen. Revenuegrowth252 two-item batch admission rejected; exact-input single runs succeeded with Sharpe-.490/-.251 andMDD26.41%/23.35%. No followups triggered.'}
    state['round20']={'plan':'round20-plan.json','sources':'ROUND19_SOURCES.md','report':'ROUND20_RESULTS.md',
        'execution_state':'round20-execution-state.json','formula_proof':'round20-signal-proof.json',
        'note':'Fixed round complete: four factors and four actual1y strategies collected, fullNAV verified. AR fails factor screen; historicalvol and lowvol controls all fail actualSharpe1.2. No3y/quarter/capital followups triggered. Controls not new families.'}
    state['factor_comparability']={'report':'FACTOR_COMPARABILITY.md','evidence':'factor-comparability-audit.json',
        'note':'Frozen samecase factor summaries compared exactly; different quantile dates diagnosed, not falsely labelled arithmetic bugs.'}
    state['candidate_dependence']={'report':'CANDIDATE_DEPENDENCE.md','evidence':'candidate-dependence.json',
        'note':'12nonduplicate passing cases,25same-date/capital daily-return pairs; correlations are descriptive, not proof of independent families or an executable combined100k account.'}
    state['round21']={'report':'ROUND21_RESULTS.md','sources':'ROUND21_SOURCES.md','new_economic_candidates':0,
        'capacity_evidence':'product-audit/round21-capacity-recovery.json','screenshot_manifest':'product-audit/round21-screenshot-manifest.json',
        'note':'Completed deferredfinancial factor collection and2growthstrategies; efficiency2strategyattempts failed resource limits. Diagnosis records publicfailure and UIevidence, not a proven RSS/cgroup cause or product fix.'}
    state['round22']={'plan':'round22-plan.json','report':'ROUND22_RESULTS.md','execution_state':'round22-execution-state.json',
        'selection_audit':'round22-selection-audit.json','note':'Nine existing positive latest-year factors, fixedH10/H20R20, all18actualyear strategies collected and all failSharpe1.2. No followups; existing formulas, no new independent families.'}
    state['round23']={'plan':'round23-plan.json','sources':'ROUND22_SOURCES.md','diagnostics':'round23-formula-diagnostics.json',
        'report':'ROUND23_RESULTS.md','execution_state':'round23-execution-state.json','formula_proof':'round23-signal-proof.json',
        'note':'Fixedroundcomplete:3factorcases collected, conditionalFIP20dayRankIC-.015447 andpairedspread-1.0764%, so failsfixedfactor gate. Bothcontrols retained, noactualstrategy or3y/quarter/capital followups. Independent120lookback proof exact for4017scores on8/27; not original11month/6month long-short replication.'}
    state['round24']={'plan':'round24-plan.json','report':'ROUND24_RESULTS.md','execution_state':'round24-execution-state.json',
        'proof':'round24-rewrite-proof.json','note':'SameQS18efficiencycase,22to11nodeequivalentrewrite verifiedsynthetically; H10stillfailedresourcelimitafter68/242research. NoResult, noH20dispatchperstoprule, no neweconomicfamily. No unchangedretry.'}
    state['round25']={'plan':'round25-plan.json','report':'ROUND25_RESULTS.md','sources':'ROUND24_SOURCES.md',
        'execution_state':'round25-execution-state.json','proof':'round25-signal-proof.json','note':'All3factorcases collected. Skew20RankIC+.014681 butq5-.048959% andpairedspread-.069162%, failsfixedfactor gate. Noactualstrategies/followups or horizon/signchange. MAX/lowvol matchingcontrols retained; notindependentfamilies.'}
    state['round26']={'plan':'round26-plan.json','report':'ROUND26_RESULTS.md','selection_audit':'round26-selection-audit.json',
        'execution_state':'round26-execution-state.json','unit_scale_comparison':'round26-unit-scale-comparison.json',
        'note':'Original20 coverageaudit:3exactlatest-year definitionsreused,1negative-equityROEsuperseded,16originaldefinitions completed. Fivepositivefactorgates ledto10H10/H20R20actualstrategies, allfailed(S-1.269to0.184,MDD23.69%to46.72%). Full242NAV/241returnintervals ofmomentumH20independentlyverified; initialverifierextrazerocorrected, noResultchange. No newformulaorfamily.'}
    state['round27']={'plan':'round27-plan.json','report':'ROUND27_RESULTS.md','sources':'ROUND26_SOURCES.md',
        'execution_state':'round27-execution-state.json','proof':'round27-signal-proof.json',
        'note':'All3factorcasescollected. FixedMRAT21/200 has20dayRankIC-.01902 despitepositiveq5andpairedspread, so fixedgatefails; noactualstrategyorhorizon/signretune. Localtwo-date16665scores exact withcommon200pricehistory; notperformance. USpaperMADthreshold/valueweightprofit notimported.'}
    state["pending_batches"] = sorted(i for i in batch_ids if i not in batches or batches[i]["status"] in ACTIVE)
    if (ROOT / 'round28-execution-state.json').exists():
        audit = json.loads((ROOT / 'round28-execution-state.json').read_text())
        state['round28'] = {'plan': 'round28-plan.json', 'report': 'ROUND28_RESULTS.md',
            'method_review': 'ROUND28_METHOD_REVIEW.md', 'execution_state': 'round28-execution-state.json',
            'status': audit['status'], 'fixed_definitions': audit['fixed_definition_count'],
            'fixed_year_cases': audit['fixed_year_cases'], 'completed_year_cases': audit['collected_year_cases'],
            'new_year_results': audit['new_year_results'], 'reused_year_results': audit['reused_year_results'],
            'unsubmitted_year_cases': len(audit['unsubmitted_year_cases']),
            'submitted_unfinished_year_cases': len(audit['submitted_unfinished_year_cases']),
            'execution_unresolved_year_cases': len(audit['execution_unresolved_year_cases']),
            'method_proof': 'round28-gate-proof.json', 'nav_audits': 'round28-nav-audits.json',
            'switch_proof': 'round28-switch-proof.json', 'switch_report': 'ROUND28_SWITCH_PROOF.md',
            'account_diagnostics': 'ROUND28_ACCOUNT_DIAGNOSTICS.md',
            'inventory_review': 'ROUND28_INVENTORY_REVIEW.md',
            'scale_proof': 'ROUND28_SCALE_PROOF.md',
            'segment3_diagnostics': 'ROUND28_SEGMENT3_DIAGNOSTICS.md',
            'admission_review': 'round28-admission-resolutions.json',
            'ui_audit': 'product-audit/ROUND28_UI_AUDIT.md',
            'metric_help_audit': 'product-audit/ROUND28_METRIC_HELP_AUDIT.md',
            'latest_checkpoint': 'round28-segment3-checkpoint-verification.json' if (ROOT / 'round28-segment3-checkpoint-verification.json').exists() else 'round28-segment2-checkpoint-verification.json',
            'name_corrections': 'round28-name-corrections.json',
            'native_year_pass_count': len(audit['native_year_passes']),
            'note': 'Finite audit of all109 previously submitted definitions, fixedH10/H20R20. No factor-performance gate. Reuse71 exact cases;143 new probes;4 prior efficiency resource cases unresolved. Old rounds remain closed; this new uniform method audit retains controls and all negative results. Do not optimize individual definitions or call examined history out-of-sample.'}
    state["pending_single_runs"] = sorted(i for i in single_ids if i not in runs or runs[i]["status"] in ACTIVE)
    state["unobserved_accepted_ids"] = sorted((batch_ids - batches.keys()) | (single_ids - runs.keys()))
    result_ids = {r["run"]["id"] for r in results}
    completed = {i for i in single_ids if i in runs and runs[i]["status"] == "succeeded"}
    for batch_id in batch_ids:
        for item in batches.get(batch_id, {}).get("items", []):
            if item["status"] == "succeeded":
                completed.add(item["research_run_id"])
    state["succeeded_but_uncollected"] = sorted(completed - result_ids)
    state["product_audit"]["issues"] = len(list((ROOT / "product-audit" / "issues").glob("*.md")))
    state["product_audit"]["screenshots"] = len([p for p in (ROOT / "product-audit" / "screenshots").iterdir() if p.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp'}])
    state["uncertainty_report"] = "SHARPE_UNCERTAINTY.md"
    state["round7"] = {"plan": "round7-plan.json", "new_unique_factor_cases": 22,
                       "accepted_task_attempts": sum(len(s["input"].get("factors", [])) for s in accepted if s["key"].startswith("r7-")),
                       "note": "Industry12 admission rejected. None10 and industry financial6 runtime resource_exhausted; all 4/4/2 and 4/2 recoveries succeeded. Same research cases, not extra hypotheses."}
    audit_path = ROOT/'capital-replay-audit.json'
    if audit_path.exists():
        offline=json.loads(audit_path.read_text())
        state['offline_capital_research']={
            'report':'CAPITAL_REPLAY.md','verified_model_runs':len(offline),
            'verified_100k_model_runs':sum(r['capital']==100000 for r in offline),
            'source_end':max(r['end'] for r in offline),
            'model':'synthetic_total_return; not full broker account',
            'above_sharpe_1_2':[r['file'] for r in offline if r['capital']==100000 and r['sharpe']>1.2],
            'latest_data_export':'awaiting explicit user approval after automatic approval review rejection; do not retry, split, or use another transfer route without approval',
            'board_access':'user question pending; all-platform and main-only scenarios kept separate'}
    state["next_actions"] = [
        "Refresh latest MCP context and poll pending durable IDs. Never restart active/unknown jobs on observation timeout. Follow retry guidance without constant two-second polling.",
        "Collect succeeded_but_uncollected plus newly succeeded runs. Capture run, strategy_summary where applicable, factor, provenance. Source of truth is accepted submissions, not arbitrary runs/ diagnostic files.",
        "Nine QS4 state rules, all static controls, original20 and round7 factors are collected. Do not restart completed or failed original attempts; recovered variants are separate evidence.",
        "Review CAPITAL_REPLAY.md and the cash-gate sensitivity plan. Local real data ends2026-08-27. Latest snapshot export to research directory is awaiting explicit user approval after auto-review rejection. Do not bypass or assume approval.",
        "For new promising economically distinct signals use limited actual strategy executions, verify topN tails, fees, coverage and multiple periods. Industry residual Alpha does not imply industry-neutral holdings.",
        "QS10/11/12 are all collected. MA60/120 and weak-lowvol did not pass predeclared followups. Do not restart or count parameter variants as independent families.",
        "QS13/14/15 are complete. Six new factors, actual strategies and WQ006 followups collected. WQ006 strong H20R10 passes native1y but fails native3y/recent/neighbor and100k cost stress. Fixed90percentile controls fail; do not optimize further percentiles.",
        "QS16 all8 native cases and18 localcapital cases are complete; inspect MARKET_SWITCH.md and independent proof. The two common-validity cash controls duplicate old242observation paths and are not new signals. All native1y/quarter and3y observations collected.",
        "QS17 all8 cases and fullNAV are collected. All4 neighbors fail year+quarter joint screen. No additional frequencies or thresholds under this plan; inspect SWITCH_NEIGHBORS.md and REGIME_ACCOUNT_ATTRIBUTION.md.",
        "QS18 all6factors collected. Efficiencychange passed fixed factor screen, but exactformula strategy batch rejected capacity and H10/H20 singles failed resource limits after4research days. Keep required actualstrategies unresolved; do not resubmit same failed input, shrinkTOP3000, shorten252warmup or claim economic failure. Any recovery needs evidence of a changed execution condition or a separately proven semantics-preserving approach.",
        "QS19 all14year strategies for7preselected existing positive factors collected; all failSharpe1.2. Growth252noneH10/H20 exact-input single recovery succeeded afterbatchrejection. No further3y/quarter/capital validation triggered by this fixedround.",
        "QS20 complete: four factor cases and four actual year strategies with fullNAV. AR fails prescreen; historicalvolH10/H20 Sharpe.288/.538 andMDD32.39%/27.81%, both fail. Matchedlowvol controls also below1.2. No further windows/signs/frequencies underplan; localproof is algebra, not profitability.",
        "QS21sources retained0newcandidates after economic and DSL dedup. Do not manufacture newfamilies through renamed proxies. CANDIDATE_DEPENDENCE contains25sameperiod/capital pairs; no portfolio fit or future independence claim.",
        "QS22 all18actualyear strategies for9remaining existing positive factors collected; all fail. Fullselectioninventory and exactinputs retained. No additionalperiods or optimization triggered.",
        "QS23 complete: conditionalFIP plus2controls collected. Candidate20dayRankIC-.015447,pairedspread-1.0764%,factor gatefails. Noactualstrategies/followups or window/sign/winnerthreshold changes; do not reinterpret positiveq5 alone as pass. Latest100k remainsunproven.",
        "QS24equivalentfinancialrewritefailedafter68researchsessions; 22to11nodes andexactsyntheticalpha do notproveRSS savings orsuccessfulrealexecution. NoResult; neitherrepeatnorH20dispatchafterfailure. QS18economiccase stillunresolved andrequiresdifferentexecutioncondition.",
        "QS25complete:3factorcases collected; skew20RankICpositivebutq5andpairedspreadnegative, noactualstrategiesorfollowups. 1/5daypositiveevidence retained withoutswitchingthefixed20daygate. MAX/lowvolcontrolsnotnewfamilies; sourcepaperlonglegunknown. Local5dateproof44616scores isformulaonly.",
        "QS26complete:original20latest-yearcoverageaudit filled16unchangeddefinitions;3exactyearcasesreused and1rawROEdefinition superseded. Fivepassedfixedfactor gatebutall10actualH10/H20R20strategiesfailedSharpe1.2andDD20%. No followupsorhorizonretune. Existingilliquidityscaledcontrolsummaryexact, notnewfamily. OnefullNAVaudituses242pointsand241adjacentreturns, neverprepend anextrazero.",
        "QS27complete:continuousMRAT21/200and2matchedcontrols collected. CandidateRankICnegativewhileq5andpairedspreadpositive; fixedgatefailsandnoactualstrategiesdispatched. Keeppositivequantiles, do notcallactualstrategynegativeoradjustthegateforasinglecandidate. Localproofverifiesscoresonly; USsourceisnotChinaperformance.",
        "Local raw market replica begins2025-08-01: one-year starts2025-09-10 cannot support60/252day warmup for new signals. Do not shorten warmup or present changed-start replay as the same case. Existing80MB export approval is pending and does not authorize an expanded earlier-history transfer.",
        "QUANTILE_COVERAGE.md proves tied scores can leave q5 empty and create different averaging dates. Local233day alpha counts are before forward-label filtering, not exact remote group coverage. No arithmetic bug claim; per-quantile and paired-spread valid dates are not returned by currentMCP.",
        "User priority remains100000CNY and20% drawdown. MCP fixed10m; offline process changes capital only and preserves the synthetic settlement model. Model checks do not prove broker-account dividends/taxes. Keep issue01/11 open, no product implementation requested.",
        "Capture complete observations limit50 for promising runs, independently recompute daily Sharpe/drawdown. Apply sharpe_uncertainty.py only to runs selected for that diagnostic; do not treat its fractions as posterior probabilities.",
        "Run analyze.py then refresh_state.py after persisting fresh observations/statuses/results. Keep negative results and exact dates; do not count variants as independent economic families.",
        "Record new product/agent interaction evidence in product-audit. Do not mark open-ended goal complete on a short-window threshold crossing."
    ]
    if 'round28' in state:
        if state['round28']['status'] == 'finite_audit_executable_phase_complete_with_unresolved':
            state['next_actions'].insert(2, 'QS28 executable fixed coverage phase is complete; inspect ROUND28_RESULTS and the segment3 checkpoint. Preserve remaining resource-unresolved cases without unchanged retries. Respect the recorded predeclared followup state. Do not retune individual definitions or infer all frequencies fail from fixedH10/H20R20. NEXT_CAPITAL_AUDIT_PREFLIGHT records48 short-market literal definitions and a possible paired100k/10m question on authorized local data through8/27; it is an inventory, not an executed test or latest-data substitute. A new bounded protocol must preserve dates/history and independently verify native common prefixes and ledger behavior; keep100k/latest limitations explicit.')
        else:
            state['next_actions'].insert(2, 'Continue the frozen QS28 finite coverage audit in first-submission order. Poll and collect existing r28 durable IDs before new submissions; reuse the71 exact frozen cases. Submit missing H10/H20R20 cases from round28-plan only, with no IC/q5/spread gate. Prior efficiency resource failures remain unresolved without unchanged retry. Record new runtime failures and stop remaining N for that definition; exact singles after reviewed batch admission rejection preserve full inputs. Native year passes trigger predeclared3y/quarter and completeNAV, never direct100k recommendation.')
    (ROOT / "SEARCH_STATE.json").write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: state[k] for k in ("submitted_tasks", "collected", "pending_batches", "pending_single_runs", "succeeded_but_uncollected")}, ensure_ascii=False))

if __name__ == "__main__":
    main()
