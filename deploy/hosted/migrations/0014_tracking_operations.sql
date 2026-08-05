CREATE TABLE thesistrace_product.tracking_equivalence_requests (
    workspace_id text NOT NULL
        DEFAULT thesistrace_control.current_workspace_id()
        REFERENCES thesistrace_control.personal_workspaces(id),
    id text PRIMARY KEY,
    daily_track_id text NOT NULL,
    generation_id text NOT NULL,
    head_checkpoint_id text NOT NULL,
    idempotency_key text NOT NULL,
    status text NOT NULL
        CHECK (
            status IN (
                'queued', 'running', 'succeeded', 'failed', 'cancelled'
            )
        ),
    result_json text,
    diagnostic_json text,
    created_at text NOT NULL,
    updated_at text NOT NULL,
    UNIQUE (workspace_id, id),
    UNIQUE (workspace_id, idempotency_key),
    FOREIGN KEY (workspace_id, daily_track_id)
        REFERENCES thesistrace_product.daily_tracks(workspace_id, id),
    FOREIGN KEY (workspace_id, generation_id)
        REFERENCES thesistrace_product.tracking_generations(workspace_id, id),
    FOREIGN KEY (workspace_id, head_checkpoint_id)
        REFERENCES thesistrace_product.tracking_checkpoints(workspace_id, id)
);

CREATE TABLE thesistrace_product.tracking_generation_rebuilds (
    workspace_id text NOT NULL
        DEFAULT thesistrace_control.current_workspace_id()
        REFERENCES thesistrace_control.personal_workspaces(id),
    id text PRIMARY KEY,
    daily_track_id text NOT NULL,
    calculation_kernel text NOT NULL,
    numeric_execution_contract text NOT NULL,
    basis_generation_id text NOT NULL,
    basis_head_checkpoint_id text NOT NULL,
    idempotency_key text NOT NULL,
    status text NOT NULL
        CHECK (
            status IN (
                'queued', 'running', 'succeeded', 'failed', 'cancelled'
            )
        ),
    generation_id text,
    advance_id text,
    diagnostic_json text,
    created_at text NOT NULL,
    updated_at text NOT NULL,
    UNIQUE (workspace_id, id),
    UNIQUE (workspace_id, idempotency_key),
    FOREIGN KEY (workspace_id, daily_track_id)
        REFERENCES thesistrace_product.daily_tracks(workspace_id, id),
    FOREIGN KEY (workspace_id, basis_generation_id)
        REFERENCES thesistrace_product.tracking_generations(workspace_id, id),
    FOREIGN KEY (workspace_id, basis_head_checkpoint_id)
        REFERENCES thesistrace_product.tracking_checkpoints(workspace_id, id),
    FOREIGN KEY (workspace_id, generation_id)
        REFERENCES thesistrace_product.tracking_generations(workspace_id, id),
    FOREIGN KEY (workspace_id, advance_id)
        REFERENCES thesistrace_product.tracking_advances(workspace_id, id)
);

ALTER TABLE thesistrace_product.tracking_equivalence_requests
ENABLE ROW LEVEL SECURITY;
ALTER TABLE thesistrace_product.tracking_equivalence_requests
FORCE ROW LEVEL SECURITY;
CREATE POLICY personal_workspace_isolation
ON thesistrace_product.tracking_equivalence_requests
USING (
    workspace_id = thesistrace_control.current_workspace_id()
)
WITH CHECK (
    workspace_id = thesistrace_control.current_workspace_id()
);

ALTER TABLE thesistrace_product.tracking_generation_rebuilds
ENABLE ROW LEVEL SECURITY;
ALTER TABLE thesistrace_product.tracking_generation_rebuilds
FORCE ROW LEVEL SECURITY;
CREATE POLICY personal_workspace_isolation
ON thesistrace_product.tracking_generation_rebuilds
USING (
    workspace_id = thesistrace_control.current_workspace_id()
)
WITH CHECK (
    workspace_id = thesistrace_control.current_workspace_id()
);

REVOKE ALL ON
    thesistrace_product.tracking_equivalence_requests,
    thesistrace_product.tracking_generation_rebuilds
FROM PUBLIC, thesistrace_api, thesistrace_compute,
     thesistrace_data, thesistrace_relay;

GRANT SELECT, INSERT, UPDATE ON
    thesistrace_product.tracking_equivalence_requests
TO thesistrace_api;

GRANT SELECT ON
    thesistrace_product.tracking_generation_rebuilds
TO thesistrace_api;

GRANT SELECT, UPDATE ON
    thesistrace_product.tracking_equivalence_requests
TO thesistrace_compute;

GRANT SELECT, INSERT, UPDATE ON
    thesistrace_product.tracking_generation_rebuilds
TO thesistrace_compute;
