BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DO $repair$
DECLARE
    target_batch_ids constant text[] := ARRAY[
        'batch_ea77c1d1361541bc9f83',
        'batch_184d9c11ad6e4f60ae3d'
    ];
    expected_generation constant text :=
        '3bc1e66cdfe2dd11721965925a4514868568b1dcfd388cce6db3ffce5c7d96b4';
    resource_diagnostic constant jsonb := jsonb_build_object(
        'code', 'RESEARCH_BATCH_RESOURCE_EXHAUSTED',
        'category', 'resource_exhausted',
        'message', 'Research Batch execution exceeded its resource limit.'
    );
    target_attempt_ids text[];
    affected integer;
BEGIN
    PERFORM 1
    FROM research_batches.batches
    WHERE id = ANY(target_batch_ids)
    ORDER BY id
    FOR UPDATE;
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 2 THEN
        RAISE EXCEPTION 'expected 2 target Batch rows, found %', affected;
    END IF;
    IF EXISTS (
        SELECT 1
        FROM research_batches.batches
        WHERE id = ANY(target_batch_ids)
          AND (
              batch_kind <> 'strategy_sweep'
              OR status <> 'running'
              OR execution_fence <> 1
              OR scope->>'data_generation_id' <> expected_generation
          )
    ) THEN
        RAISE EXCEPTION 'target Batch identity or lifecycle changed';
    END IF;

    PERFORM 1
    FROM research_batches.progress
    WHERE batch_id = ANY(target_batch_ids)
    ORDER BY batch_id
    FOR UPDATE;
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 2 OR EXISTS (
        SELECT 1
        FROM research_batches.progress
        WHERE batch_id = ANY(target_batch_ids)
          AND (
              total_items <> 3
              OR completed_items <> 0
              OR shared_alpha_factor_status <> 'pending'
          )
    ) THEN
        RAISE EXCEPTION 'target Batch progress changed';
    END IF;

    SELECT array_agg(id ORDER BY id)
    INTO target_attempt_ids
    FROM research_batches.attempts
    WHERE batch_id = ANY(target_batch_ids);
    PERFORM 1
    FROM research_batches.attempts
    WHERE batch_id = ANY(target_batch_ids)
    ORDER BY id
    FOR UPDATE;
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 2 OR cardinality(target_attempt_ids) <> 2 OR EXISTS (
        SELECT 1
        FROM research_batches.attempts
        WHERE batch_id = ANY(target_batch_ids)
          AND (
              status <> 'running'
              OR ordinal <> 1
              OR fence <> 1
              OR data_generation_id <> expected_generation
              OR child_exited_at IS NULL
              OR child_exit_code <> -9
              OR child_acknowledged IS DISTINCT FROM false
          )
    ) THEN
        RAISE EXCEPTION 'target Batch Attempt evidence changed';
    END IF;

    PERFORM 1
    FROM research_batches.task_attempts
    WHERE batch_id = ANY(target_batch_ids)
    ORDER BY id
    FOR UPDATE;
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 2 OR EXISTS (
        SELECT 1
        FROM research_batches.task_attempts
        WHERE batch_id = ANY(target_batch_ids)
          AND (
              status <> 'running'
              OR ordinal <> 1
              OR task_role <> 'shared_alpha_factor'
              OR item_ordinal IS NOT NULL
              OR batch_attempt_id <> ALL(target_attempt_ids)
          )
    ) THEN
        RAISE EXCEPTION 'target shared task Attempt evidence changed';
    END IF;

    PERFORM 1
    FROM research_batches.items
    WHERE batch_id = ANY(target_batch_ids)
    ORDER BY batch_id, ordinal
    FOR UPDATE;
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 6 OR EXISTS (
        SELECT 1
        FROM research_batches.items
        WHERE batch_id = ANY(target_batch_ids)
          AND (outcome IS NOT NULL OR diagnostic IS NOT NULL)
    ) THEN
        RAISE EXCEPTION 'target Batch items changed';
    END IF;

    PERFORM 1
    FROM research_runs.runs
    WHERE id IN (
        SELECT research_run_id
        FROM research_batches.items
        WHERE batch_id = ANY(target_batch_ids)
    )
    ORDER BY id
    FOR UPDATE;
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 6 OR EXISTS (
        SELECT 1
        FROM research_runs.runs
        WHERE id IN (
            SELECT research_run_id
            FROM research_batches.items
            WHERE batch_id = ANY(target_batch_ids)
        )
          AND (
              status <> 'running'
              OR execution_owner <> 'research_batch'
              OR result_manifest_sha256 IS NOT NULL
          )
    ) THEN
        RAISE EXCEPTION 'target child Run lifecycle changed';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM research_runs.attempts
        WHERE run_id IN (
            SELECT research_run_id
            FROM research_batches.items
            WHERE batch_id = ANY(target_batch_ids)
        )
    ) OR EXISTS (
        SELECT 1
        FROM research_runs.execution_checkpoints
        WHERE run_id IN (
            SELECT research_run_id
            FROM research_batches.items
            WHERE batch_id = ANY(target_batch_ids)
        )
    ) THEN
        RAISE EXCEPTION 'target child Run has unexpected durable execution state';
    END IF;

    PERFORM 1
    FROM data.generation_pins
    WHERE owner_kind = 'research_batch_attempt'
      AND owner_id = ANY(target_attempt_ids)
    ORDER BY id
    FOR UPDATE;
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 2 OR EXISTS (
        SELECT 1
        FROM data.generation_pins
        WHERE owner_kind = 'research_batch_attempt'
          AND owner_id = ANY(target_attempt_ids)
          AND (
              status <> 'active'
              OR generation_manifest_sha256 <> expected_generation
          )
    ) THEN
        RAISE EXCEPTION 'target Generation pins changed';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM research_batches.starting_claims
        WHERE batch_id = ANY(target_batch_ids)
    ) OR EXISTS (
        SELECT 1
        FROM research_batches.private_alpha_factor_artifacts
        WHERE batch_id = ANY(target_batch_ids)
    ) THEN
        RAISE EXCEPTION 'target Batch has unexpected starting or artifact state';
    END IF;

    UPDATE research_batches.task_attempts
    SET status = 'failed',
        finished_at = transaction_timestamp(),
        failure_reason = 'ResourceExhausted',
        failure_diagnostic = resource_diagnostic
    WHERE batch_id = ANY(target_batch_ids)
      AND batch_attempt_id = ANY(target_attempt_ids)
      AND status = 'running';
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 2 THEN
        RAISE EXCEPTION 'closed % target task Attempts, expected 2', affected;
    END IF;

    UPDATE research_batches.attempts
    SET status = 'failed',
        heartbeat_at = transaction_timestamp(),
        lease_expires_at = transaction_timestamp(),
        finished_at = transaction_timestamp(),
        failure_reason = 'ResourceExhausted',
        failure_diagnostic = resource_diagnostic,
        current_task_role = NULL,
        current_item_key = NULL,
        current_phase = NULL,
        completed_research_sessions = NULL,
        total_research_sessions = NULL,
        task_started_at = NULL,
        live_progress_updated_at = NULL
    WHERE id = ANY(target_attempt_ids)
      AND batch_id = ANY(target_batch_ids)
      AND status = 'running';
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 2 THEN
        RAISE EXCEPTION 'closed % target Batch Attempts, expected 2', affected;
    END IF;

    UPDATE research_runs.runs
    SET status = 'failed',
        execution_fence = execution_fence + 1,
        failure_reason = 'Research Batch execution exceeded its resource limit.',
        updated_at = transaction_timestamp()
    WHERE id IN (
        SELECT research_run_id
        FROM research_batches.items
        WHERE batch_id = ANY(target_batch_ids)
    )
      AND status = 'running'
      AND execution_owner = 'research_batch';
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 6 THEN
        RAISE EXCEPTION 'closed % target child Runs, expected 6', affected;
    END IF;

    UPDATE research_runs.progress
    SET remaining_duration_estimate_seconds = NULL,
        updated_at = transaction_timestamp()
    WHERE run_id IN (
        SELECT research_run_id
        FROM research_batches.items
        WHERE batch_id = ANY(target_batch_ids)
    );
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 6 THEN
        RAISE EXCEPTION 'updated % target child progress rows, expected 6', affected;
    END IF;

    UPDATE research_batches.items
    SET outcome = 'failed', diagnostic = resource_diagnostic
    WHERE batch_id = ANY(target_batch_ids)
      AND outcome IS NULL;
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 6 THEN
        RAISE EXCEPTION 'closed % target Batch items, expected 6', affected;
    END IF;

    UPDATE research_batches.progress
    SET completed_items = total_items,
        shared_alpha_factor_status = 'failed',
        updated_at = transaction_timestamp()
    WHERE batch_id = ANY(target_batch_ids)
      AND completed_items = 0
      AND total_items = 3
      AND shared_alpha_factor_status = 'pending';
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 2 THEN
        RAISE EXCEPTION 'closed % target Batch progress rows, expected 2', affected;
    END IF;

    UPDATE data.generation_pins
    SET status = 'released',
        lease_expires_at = transaction_timestamp(),
        heartbeat_at = transaction_timestamp(),
        released_at = transaction_timestamp()
    WHERE owner_kind = 'research_batch_attempt'
      AND owner_id = ANY(target_attempt_ids)
      AND status = 'active';
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 2 THEN
        RAISE EXCEPTION 'released % target Generation pins, expected 2', affected;
    END IF;

    UPDATE research_batches.batches
    SET status = 'failed', updated_at = transaction_timestamp()
    WHERE id = ANY(target_batch_ids)
      AND status = 'running'
      AND execution_fence = 1;
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 2 THEN
        RAISE EXCEPTION 'closed % target Batch rows, expected 2', affected;
    END IF;

    IF (
        SELECT count(*)
        FROM research_batches.batches
        WHERE id = ANY(target_batch_ids) AND status = 'failed'
    ) <> 2 OR (
        SELECT count(*)
        FROM research_batches.items
        WHERE batch_id = ANY(target_batch_ids)
          AND outcome = 'failed'
          AND diagnostic = resource_diagnostic
    ) <> 6 OR (
        SELECT count(*)
        FROM data.generation_pins
        WHERE owner_kind = 'research_batch_attempt'
          AND owner_id = ANY(target_attempt_ids)
          AND status = 'released'
    ) <> 2 THEN
        RAISE EXCEPTION 'target repair postcondition failed';
    END IF;
END
$repair$;

SELECT batch.id,
       batch.status,
       progress.completed_items,
       progress.total_items,
       progress.shared_alpha_factor_status,
       count(*) FILTER (WHERE item.outcome = 'failed') AS failed_items,
       count(DISTINCT pin.id) FILTER (WHERE pin.status = 'released') AS released_pins
FROM research_batches.batches AS batch
JOIN research_batches.progress AS progress ON progress.batch_id = batch.id
JOIN research_batches.items AS item ON item.batch_id = batch.id
JOIN research_batches.attempts AS attempt ON attempt.batch_id = batch.id
JOIN data.generation_pins AS pin ON pin.id = attempt.generation_pin_id
WHERE batch.id IN (
    'batch_ea77c1d1361541bc9f83',
    'batch_184d9c11ad6e4f60ae3d'
)
GROUP BY batch.id, batch.status, progress.completed_items,
         progress.total_items, progress.shared_alpha_factor_status
ORDER BY batch.id;

COMMIT;
