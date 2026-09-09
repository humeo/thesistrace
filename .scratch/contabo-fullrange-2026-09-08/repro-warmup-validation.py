from thesistrace.research_kernel.research_chunks import empty_research_continuation, validated_research_continuation
for sessions in ([], ['2010-01-05']):
    state=empty_research_continuation('strategy_backtest')
    state['rolling_tail_sessions']=sessions
    try:
        validated_research_continuation(state,research_kind='strategy_backtest')
        print({'rolling_tail_sessions':sessions,'validation':'passed'})
    except ValueError as error:
        print({'rolling_tail_sessions':sessions,'validation':'failed','error':str(error)})
