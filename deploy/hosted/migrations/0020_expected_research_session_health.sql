CREATE FUNCTION thesistrace_control.dataset_release_matches_expected_session()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, thesistrace_product
AS $$
    WITH current_release AS (
        SELECT release.manifest_json::jsonb AS manifest
        FROM thesistrace_product.dataset_release_pointer AS pointer
        JOIN thesistrace_product.dataset_releases AS release
          ON release.id = pointer.release_id
        WHERE pointer.singleton = 1
    ),
    expected_session AS (
        SELECT publication.parameters_json ->> 'as_of' AS session
        FROM thesistrace_product.dataset_publications AS publication
        WHERE publication.trigger_kind = 'schedule'
          AND publication.kind IN ('live_bootstrap', 'live_increment')
        ORDER BY publication.created_at::timestamptz DESC
        LIMIT 1
    )
    SELECT COALESCE(
        (
            SELECT expected.session IS NULL
                OR release.manifest #>> '{appended_session_range,end}'
                    >= expected.session
            FROM current_release AS release
            LEFT JOIN expected_session AS expected ON true
        ),
        false
    )
$$;

REVOKE ALL ON FUNCTION
thesistrace_control.dataset_release_matches_expected_session()
FROM PUBLIC, thesistrace_api, thesistrace_relay,
     thesistrace_data, thesistrace_compute;
GRANT EXECUTE ON FUNCTION
thesistrace_control.dataset_release_matches_expected_session()
TO thesistrace_health;
