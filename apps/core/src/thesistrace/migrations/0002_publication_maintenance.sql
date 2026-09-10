CREATE TABLE publication.maintenance_state (
    job text PRIMARY KEY CHECK (job IN ('queued_deletions', 'orphan_scan')),
    next_due_at timestamptz NOT NULL DEFAULT now(),
    last_key text NOT NULL DEFAULT '',
    sweep_started_at timestamptz,
    cutoff timestamptz,
    last_sweep_completed_at timestamptz,
    failure_count integer NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
    last_error text,
    CHECK ((sweep_started_at IS NULL) = (cutoff IS NULL)),
    CHECK (job = 'orphan_scan' OR (last_key = '' AND cutoff IS NULL)),
    CHECK (cutoff IS NOT NULL OR last_key = '')
);

INSERT INTO publication.maintenance_state (job) VALUES ('queued_deletions'), ('orphan_scan');
