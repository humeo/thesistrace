-- Frozen pre-index list query, used only for performance comparison.

                    WITH filtered AS NOT MATERIALIZED (
                        SELECT id, name, folder_id, status, requested_start_date,
                               requested_end_date, created_at, immutable_input,
                               key_metrics, failure_reason
                        FROM research_runs.runs
                        WHERE researcher_id = %s
                          AND (%s::text IS NULL OR folder_id = %s::text)
                          AND (%s::text IS NULL OR immutable_input->>'research_kind' = %s::text)
                          AND (%s::text = ''
                               OR strpos(lower(name), lower(%s::text)) > 0
                               OR strpos(lower(immutable_input->>'hypothesis'), lower(%s::text)) > 0
                               OR strpos(lower(immutable_input->>'formula_source'),
                                         lower(%s::text)) > 0)
                    )
                    SELECT totals.total_count, page_rows.*
                    FROM (SELECT count(*) AS total_count FROM filtered) AS totals
                    LEFT JOIN LATERAL (
                        SELECT *, created_at AS sort_value FROM filtered
                        ORDER BY sort_value DESC NULLS LAST, created_at DESC, id
                        LIMIT %s OFFSET %s
                    ) AS page_rows ON true
                    ORDER BY page_rows.sort_value DESC NULLS LAST,
                             page_rows.created_at DESC, page_rows.id
