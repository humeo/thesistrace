CONSTRAINT runs_key_metrics_check CHECK (
        key_metrics IS NULL
        OR (
            jsonb_typeof(key_metrics) = 'object'::text
            AND key_metrics->>'research_kind' = immutable_input->>'research_kind'
            AND (
                (
                    key_metrics->>'research_kind' = 'factor_evaluation'
                    AND key_metrics ?& ARRAY[
                        'one_session_rank_ic',
                        'five_session_rank_ic',
                        'twenty_session_rank_ic'
                    ]
                    AND key_metrics - ARRAY[
                        'research_kind',
                        'one_session_rank_ic',
                        'five_session_rank_ic',
                        'twenty_session_rank_ic'
                    ] = '{}'::jsonb
                )
                OR (
                    key_metrics->>'research_kind' = 'strategy_backtest'
                    AND key_metrics ?& ARRAY[
                        'annualized_excess_return',
                        'sharpe',
                        'maximum_drawdown'
                    ]
                    AND key_metrics - ARRAY[
                        'research_kind',
                        'annualized_excess_return',
                        'sharpe',
                        'maximum_drawdown'
                    ] = '{}'::jsonb
                )
            )
        )
    )
