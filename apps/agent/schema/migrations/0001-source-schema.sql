CREATE TABLE agent.model_charge (
    id uuid PRIMARY KEY,
    researcher_id uuid NOT NULL,
    budget_day date NOT NULL,
    reserved_nanodollars bigint NOT NULL CHECK (reserved_nanodollars >= 0),
    actual_nanodollars bigint CHECK (actual_nanodollars >= 0),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE INDEX model_charge_researcher_day ON agent.model_charge (researcher_id, budget_day);

CREATE TABLE agent."mastra_threads" (
    "id" text NOT NULL,
    "resourceId" text NOT NULL,
    "title" text NOT NULL,
    "metadata" jsonb,
    "createdAt" timestamp without time zone NOT NULL,
    "updatedAt" timestamp without time zone NOT NULL,
    "createdAtZ" timestamp with time zone DEFAULT pg_catalog.now(),
    "updatedAtZ" timestamp with time zone DEFAULT pg_catalog.now(),
    CONSTRAINT mastra_threads_pkey PRIMARY KEY ("id")
);

CREATE TABLE agent."mastra_messages" (
    "id" text NOT NULL,
    "thread_id" text NOT NULL,
    "content" text NOT NULL,
    "role" text NOT NULL,
    "type" text NOT NULL,
    "createdAt" timestamp without time zone NOT NULL,
    "resourceId" text,
    "createdAtZ" timestamp with time zone DEFAULT pg_catalog.now(),
    CONSTRAINT mastra_messages_pkey PRIMARY KEY ("id")
);

CREATE TABLE agent."mastra_resources" (
    "id" text NOT NULL,
    "workingMemory" text,
    "metadata" jsonb,
    "createdAt" timestamp without time zone NOT NULL,
    "updatedAt" timestamp without time zone NOT NULL,
    "createdAtZ" timestamp with time zone DEFAULT pg_catalog.now(),
    "updatedAtZ" timestamp with time zone DEFAULT pg_catalog.now(),
    CONSTRAINT mastra_resources_pkey PRIMARY KEY ("id")
);

CREATE TABLE agent."mastra_observational_memory" (
    "id" text NOT NULL,
    "lookupKey" text NOT NULL,
    "scope" text NOT NULL,
    "resourceId" text,
    "threadId" text,
    "activeObservations" text NOT NULL,
    "activeObservationsPendingUpdate" text,
    "originType" text NOT NULL,
    "config" text NOT NULL,
    "generationCount" integer NOT NULL,
    "lastObservedAt" timestamp without time zone,
    "lastReflectionAt" timestamp without time zone,
    "pendingMessageTokens" integer NOT NULL,
    "totalTokensObserved" integer NOT NULL,
    "observationTokenCount" integer NOT NULL,
    "isObserving" boolean NOT NULL,
    "isReflecting" boolean NOT NULL,
    "observedMessageIds" jsonb,
    "observedTimezone" text,
    "bufferedObservations" text,
    "bufferedObservationTokens" integer,
    "bufferedMessageIds" jsonb,
    "bufferedReflection" text,
    "bufferedReflectionTokens" integer,
    "bufferedReflectionInputTokens" integer,
    "reflectedObservationLineCount" integer,
    "bufferedObservationChunks" jsonb,
    "isBufferingObservation" boolean NOT NULL,
    "isBufferingReflection" boolean NOT NULL,
    "lastBufferedAtTokens" integer NOT NULL,
    "lastBufferedAtTime" timestamp without time zone,
    "metadata" jsonb,
    "createdAt" timestamp without time zone NOT NULL,
    "updatedAt" timestamp without time zone NOT NULL,
    "lastObservedAtZ" timestamp with time zone DEFAULT pg_catalog.now(),
    "lastReflectionAtZ" timestamp with time zone DEFAULT pg_catalog.now(),
    "lastBufferedAtTimeZ" timestamp with time zone DEFAULT pg_catalog.now(),
    "createdAtZ" timestamp with time zone DEFAULT pg_catalog.now(),
    "updatedAtZ" timestamp with time zone DEFAULT pg_catalog.now(),
    CONSTRAINT mastra_observational_memory_pkey PRIMARY KEY ("id")
);

CREATE TABLE agent."mastra_workflow_snapshot" (
    "workflow_name" text NOT NULL,
    "run_id" text NOT NULL,
    "resourceId" text,
    "snapshot" jsonb NOT NULL,
    "createdAt" timestamp without time zone NOT NULL,
    "updatedAt" timestamp without time zone NOT NULL,
    "createdAtZ" timestamp with time zone DEFAULT pg_catalog.now(),
    "updatedAtZ" timestamp with time zone DEFAULT pg_catalog.now(),
    CONSTRAINT agent_mastra_workflow_snapshot_workflow_name_run_id_key
        UNIQUE ("workflow_name", "run_id")
);

ALTER TABLE agent."mastra_workflow_snapshot"
    REPLICA IDENTITY USING INDEX
    agent_mastra_workflow_snapshot_workflow_name_run_id_key;

CREATE TABLE agent.chat_session (
    id uuid NOT NULL,
    researcher_id uuid NOT NULL,
    selected_model_key text NOT NULL,
    selected_reasoning_effort text NOT NULL,
    created_at timestamp with time zone DEFAULT pg_catalog.now() NOT NULL,
    updated_at timestamp with time zone DEFAULT pg_catalog.now() NOT NULL,
    CONSTRAINT chat_session_pkey PRIMARY KEY (id),
    CONSTRAINT chat_session_model_key_check CHECK (
        selected_model_key ~ '^[a-z0-9][a-z0-9._-]{0,63}$'::text
    ),
    CONSTRAINT chat_session_reasoning_effort_check CHECK (
        selected_reasoning_effort = ANY (
            ARRAY['none'::text, 'minimal'::text, 'low'::text, 'medium'::text, 'high'::text, 'xhigh'::text, 'max'::text]
        )
    )
);

CREATE TABLE agent.agent_run (
    id uuid NOT NULL,
    thread_id uuid NOT NULL,
    kind text NOT NULL,
    request_fingerprint bytea NOT NULL,
    model_key text NOT NULL,
    provider_model_id text NOT NULL,
    reasoning_effort text NOT NULL,
    agent_build_revision text NOT NULL,
    status text NOT NULL,
    token_usage jsonb,
    step_count integer DEFAULT 0 NOT NULL,
    generated_bytes integer DEFAULT 0 NOT NULL,
    terminal_error_code text,
    started_at timestamp with time zone DEFAULT pg_catalog.now() NOT NULL,
    completed_at timestamp with time zone,
    CONSTRAINT agent_run_pkey PRIMARY KEY (id),
    CONSTRAINT agent_run_thread_id_id_key UNIQUE (thread_id, id),
    CONSTRAINT agent_run_thread_id_fkey FOREIGN KEY (thread_id)
        REFERENCES agent.chat_session(id) ON DELETE CASCADE,
    CONSTRAINT agent_run_request_fingerprint_check CHECK (
        pg_catalog.octet_length(request_fingerprint) = 32
    ),
    CONSTRAINT agent_run_kind_check CHECK (
        kind = ANY (ARRAY['prompt'::text, 'continue'::text])
    ),
    CONSTRAINT agent_run_model_key_check CHECK (
        model_key ~ '^[a-z0-9][a-z0-9._-]{0,63}$'::text
    ),
    CONSTRAINT agent_run_provider_model_id_check CHECK (
        provider_model_id = pg_catalog.btrim(provider_model_id)
        AND pg_catalog.char_length(provider_model_id) BETWEEN 1 AND 200
    ),
    CONSTRAINT agent_run_reasoning_effort_check CHECK (
        reasoning_effort = ANY (
            ARRAY['none'::text, 'minimal'::text, 'low'::text, 'medium'::text, 'high'::text, 'xhigh'::text, 'max'::text]
        )
    ),
    CONSTRAINT agent_run_build_revision_check CHECK (
        agent_build_revision = pg_catalog.btrim(agent_build_revision)
        AND pg_catalog.char_length(agent_build_revision) BETWEEN 1 AND 128
    ),
    CONSTRAINT agent_run_status_check CHECK (
        status = ANY (
            ARRAY[
                'running'::text,
                'waiting_for_user'::text,
                'stopping'::text,
                'completed'::text,
                'stopped'::text,
                'failed'::text
            ]
        )
    ),
    CONSTRAINT agent_run_budget_check CHECK (
        step_count >= 0
        AND generated_bytes BETWEEN 0 AND 262144
    ),
    CONSTRAINT agent_run_terminal_check CHECK (
        (
            status = 'running'::text
            AND completed_at IS NULL
            AND token_usage IS NULL
            AND terminal_error_code IS NULL
        ) OR (
            status = 'waiting_for_user'::text
            AND completed_at IS NULL
            AND token_usage IS NOT NULL
            AND terminal_error_code IS NULL
        ) OR (
            status = 'stopping'::text
            AND completed_at IS NULL
            AND terminal_error_code IS NULL
        ) OR (
            status = 'completed'::text
            AND completed_at IS NOT NULL
            AND token_usage IS NOT NULL
            AND terminal_error_code IS NULL
        ) OR (
            status = 'stopped'::text
            AND completed_at IS NOT NULL
            AND token_usage IS NOT NULL
            AND terminal_error_code IS NULL
        ) OR (
            status = 'failed'::text
            AND completed_at IS NOT NULL
            AND token_usage IS NOT NULL
            AND terminal_error_code IS NOT NULL
        )
    )
);

CREATE TABLE agent.chat_command (
    thread_id uuid NOT NULL,
    id uuid NOT NULL,
    turn_id uuid NOT NULL,
    kind text NOT NULL,
    request_fingerprint bytea NOT NULL,
    status text NOT NULL,
    error_code text,
    created_at timestamp with time zone DEFAULT pg_catalog.now() NOT NULL,
    updated_at timestamp with time zone DEFAULT pg_catalog.now() NOT NULL,
    CONSTRAINT chat_command_pkey PRIMARY KEY (thread_id, id),
    CONSTRAINT chat_command_thread_id_fkey FOREIGN KEY (thread_id)
        REFERENCES agent.chat_session(id) ON DELETE CASCADE,
    CONSTRAINT chat_command_turn_fkey FOREIGN KEY (thread_id, turn_id)
        REFERENCES agent.agent_run(thread_id, id) ON DELETE CASCADE,
    CONSTRAINT chat_command_kind_check CHECK (
        kind = ANY (
            ARRAY[
                'prompt'::text,
                'continue'::text,
                'steer'::text,
                'answer'::text,
                'stop'::text
            ]
        )
    ),
    CONSTRAINT chat_command_request_fingerprint_check CHECK (
        pg_catalog.octet_length(request_fingerprint) = 32
    ),
    CONSTRAINT chat_command_status_check CHECK (
        status = ANY (ARRAY['pending'::text, 'accepted'::text, 'rejected'::text])
    ),
    CONSTRAINT chat_command_outcome_check CHECK (
        (status = 'rejected'::text AND error_code IS NOT NULL)
        OR (status <> 'rejected'::text AND error_code IS NULL)
    ),
    CONSTRAINT chat_command_error_code_check CHECK (
        error_code IS NULL OR (
            error_code = pg_catalog.btrim(error_code)
            AND pg_catalog.char_length(error_code) BETWEEN 1 AND 80
        )
    ),
    CONSTRAINT chat_command_timestamps_check CHECK (updated_at >= created_at)
);

CREATE TABLE agent.chat_interrupt (
    thread_id uuid NOT NULL,
    id text NOT NULL,
    turn_id uuid NOT NULL,
    tool_call_id text NOT NULL,
    question text NOT NULL,
    options jsonb,
    selection_mode text NOT NULL,
    status text NOT NULL,
    answer_command_id uuid,
    created_at timestamp with time zone DEFAULT pg_catalog.now() NOT NULL,
    answered_at timestamp with time zone,
    CONSTRAINT chat_interrupt_pkey PRIMARY KEY (thread_id, id),
    CONSTRAINT chat_interrupt_thread_id_fkey FOREIGN KEY (thread_id)
        REFERENCES agent.chat_session(id) ON DELETE CASCADE,
    CONSTRAINT chat_interrupt_turn_fkey FOREIGN KEY (thread_id, turn_id)
        REFERENCES agent.agent_run(thread_id, id) ON DELETE CASCADE,
    CONSTRAINT chat_interrupt_answer_command_fkey FOREIGN KEY (thread_id, answer_command_id)
        REFERENCES agent.chat_command(thread_id, id),
    CONSTRAINT chat_interrupt_id_check CHECK (
        pg_catalog.char_length(id) BETWEEN 1 AND 800
        AND id !~ '[[:cntrl:]]'::text
    ),
    CONSTRAINT chat_interrupt_tool_call_id_check CHECK (
        pg_catalog.char_length(tool_call_id) BETWEEN 1 AND 512
        AND tool_call_id !~ '[[:cntrl:]]'::text
    ),
    CONSTRAINT chat_interrupt_question_check CHECK (
        question = pg_catalog.btrim(question)
        AND pg_catalog.octet_length(question) BETWEEN 1 AND 4096
    ),
    CONSTRAINT chat_interrupt_options_check CHECK (
        options IS NULL OR (
            pg_catalog.jsonb_typeof(options) = 'array'::text
            AND pg_catalog.octet_length(options::text) <= 65536
        )
    ),
    CONSTRAINT chat_interrupt_selection_mode_check CHECK (
        selection_mode = ANY (
            ARRAY['free_text'::text, 'single_select'::text, 'multi_select'::text]
        )
    ),
    CONSTRAINT chat_interrupt_status_check CHECK (
        status = ANY (ARRAY['pending'::text, 'answered'::text, 'stopped'::text])
    ),
    CONSTRAINT chat_interrupt_outcome_check CHECK (
        (
            status = 'pending'::text
            AND answer_command_id IS NULL
            AND answered_at IS NULL
        ) OR (
            status = 'answered'::text
            AND answer_command_id IS NOT NULL
            AND answered_at IS NOT NULL
        ) OR (
            status = 'stopped'::text
            AND answer_command_id IS NULL
            AND answered_at IS NOT NULL
        )
    )
);

CREATE TABLE agent.chat_timeline_entry (
    thread_id uuid NOT NULL,
    entry_id text NOT NULL,
    sequence bigint GENERATED ALWAYS AS IDENTITY,
    turn_id uuid NOT NULL,
    kind text NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT pg_catalog.now() NOT NULL,
    updated_at timestamp with time zone DEFAULT pg_catalog.now() NOT NULL,
    CONSTRAINT chat_timeline_entry_pkey PRIMARY KEY (thread_id, entry_id),
    CONSTRAINT chat_timeline_entry_sequence_key UNIQUE (sequence),
    CONSTRAINT chat_timeline_entry_thread_id_fkey FOREIGN KEY (thread_id)
        REFERENCES agent.chat_session(id) ON DELETE CASCADE,
    CONSTRAINT chat_timeline_entry_turn_fkey FOREIGN KEY (thread_id, turn_id)
        REFERENCES agent.agent_run(thread_id, id) ON DELETE CASCADE,
    CONSTRAINT chat_timeline_entry_id_check CHECK (
        pg_catalog.char_length(entry_id) BETWEEN 1 AND 800
        AND entry_id !~ '[[:cntrl:]]'::text
    ),
    CONSTRAINT chat_timeline_entry_kind_check CHECK (
        kind = ANY (
            ARRAY[
                'user_input'::text,
                'assistant_message'::text,
                'tool_activity'::text,
                'a2ui'::text,
                'question'::text,
                'turn_outcome'::text
            ]
        )
    ),
    CONSTRAINT chat_timeline_entry_payload_check CHECK (
        pg_catalog.jsonb_typeof(payload) = 'object'::text
        AND pg_catalog.octet_length(payload::text) <= 524288
    ),
    CONSTRAINT chat_timeline_entry_timestamps_check CHECK (updated_at >= created_at)
);

CREATE TABLE agent.a2ui_message (
    thread_id uuid NOT NULL,
    id text NOT NULL,
    run_id uuid NOT NULL,
    owner_message_id text NOT NULL,
    activity_type text NOT NULL,
    protocol_version text NOT NULL,
    catalog_id text NOT NULL,
    lifecycle_status text NOT NULL,
    sequence integer NOT NULL,
    content jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT pg_catalog.now() NOT NULL,
    updated_at timestamp with time zone DEFAULT pg_catalog.now() NOT NULL,
    CONSTRAINT a2ui_message_pkey PRIMARY KEY (thread_id, id),
    CONSTRAINT a2ui_message_thread_id_fkey FOREIGN KEY (thread_id)
        REFERENCES agent.chat_session(id) ON DELETE CASCADE,
    CONSTRAINT a2ui_message_run_id_fkey FOREIGN KEY (run_id)
        REFERENCES agent.agent_run(id) ON DELETE CASCADE,
    CONSTRAINT a2ui_message_owner_message_id_fkey FOREIGN KEY (owner_message_id)
        REFERENCES agent."mastra_messages"(id) ON DELETE CASCADE,
    CONSTRAINT a2ui_message_run_sequence_key UNIQUE (run_id, sequence),
    CONSTRAINT a2ui_message_id_check CHECK (
        id ~ '^a2ui-surface-[A-Za-z0-9._:-]{1,200}$'::text
    ),
    CONSTRAINT a2ui_message_owner_message_id_check CHECK (
        pg_catalog.char_length(owner_message_id) BETWEEN 1 AND 220
        AND owner_message_id !~ '[[:cntrl:]]'::text
    ),
    CONSTRAINT a2ui_message_activity_type_check CHECK (
        activity_type = 'a2ui-surface'::text
    ),
    CONSTRAINT a2ui_message_protocol_version_check CHECK (
        protocol_version = 'v0.9'::text
    ),
    CONSTRAINT a2ui_message_catalog_id_check CHECK (
        catalog_id = 'urn:thesistrace:a2ui:research:v0.9'::text
    ),
    CONSTRAINT a2ui_message_lifecycle_status_check CHECK (
        lifecycle_status = ANY (
            ARRAY['loading'::text, 'ready'::text, 'error'::text]
        )
    ),
    CONSTRAINT a2ui_message_sequence_check CHECK (sequence BETWEEN 1 AND 1000000),
    CONSTRAINT a2ui_message_content_check CHECK (
        pg_catalog.jsonb_typeof(content) = 'object'::text
        -- The shared ingress contract is 64 KiB of compact JSON. PostgreSQL's
        -- jsonb text adds insignificant spaces, so this storage bound must not
        -- reject a valid ingress payload merely because of serialization.
        AND pg_catalog.octet_length(content::text) <= 131072
    ),
    CONSTRAINT a2ui_message_timestamps_check CHECK (updated_at >= created_at)
);

CREATE TABLE agent.schema_contract (
    singleton boolean NOT NULL,
    schema_fingerprint text NOT NULL,
    CONSTRAINT schema_contract_pkey PRIMARY KEY (singleton),
    CONSTRAINT schema_contract_singleton_check CHECK (singleton),
    CONSTRAINT schema_contract_schema_fingerprint_check CHECK (
        schema_fingerprint ~ '^[0-9a-f]{64}$'::text
    )
);

CREATE INDEX agent_idx_om_lookup_key
    ON agent."mastra_observational_memory" USING btree ("lookupKey");
CREATE INDEX agent_mastra_threads_resourceid_createdat_idx
    ON agent."mastra_threads" USING btree ("resourceId", "createdAt" DESC);
CREATE INDEX agent_mastra_messages_thread_id_createdat_idx
    ON agent."mastra_messages" USING btree (thread_id, "createdAt" DESC);
CREATE INDEX agent_mastra_workflow_snapshot_name_createdat_idx
    ON agent."mastra_workflow_snapshot" USING btree ("workflow_name", "createdAt" DESC);
CREATE INDEX agent_mastra_workflow_snapshot_name_status_createdat_idx
    ON agent."mastra_workflow_snapshot" USING btree (
        "workflow_name",
        (("snapshot" ->> 'status'::text)),
        "createdAt" DESC
    );
CREATE INDEX chat_session_researcher_activity_idx
    ON agent.chat_session USING btree (researcher_id, updated_at DESC, id DESC);
CREATE INDEX agent_run_thread_started_idx
    ON agent.agent_run USING btree (thread_id, started_at, id);
CREATE UNIQUE INDEX agent_run_one_current_per_thread_idx
    ON agent.agent_run USING btree (thread_id)
    WHERE status = ANY (
        ARRAY['running'::text, 'waiting_for_user'::text, 'stopping'::text]
    );
CREATE INDEX chat_command_turn_created_idx
    ON agent.chat_command USING btree (thread_id, turn_id, created_at, id);
CREATE UNIQUE INDEX chat_interrupt_one_pending_per_turn_idx
    ON agent.chat_interrupt USING btree (turn_id)
    WHERE status = 'pending'::text;
CREATE INDEX chat_timeline_thread_sequence_idx
    ON agent.chat_timeline_entry USING btree (thread_id, sequence DESC);
CREATE INDEX a2ui_message_owner_idx
    ON agent.a2ui_message USING btree (thread_id, owner_message_id, sequence, id);

CREATE TABLE agent.session_context_checkpoint (
    thread_id uuid PRIMARY KEY REFERENCES agent.chat_session(id) ON DELETE CASCADE,
    revision integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
    snapshot jsonb,
    cycle_id uuid,
    cycle_run_id uuid REFERENCES agent.agent_run(id),
    CHECK ((revision = 0 AND snapshot IS NULL) OR (revision > 0 AND snapshot IS NOT NULL AND jsonb_typeof(snapshot) = 'object')),
    CHECK ((cycle_id IS NULL) = (cycle_run_id IS NULL))
);

CREATE TABLE agent.model_step_recovery (
    thread_id uuid NOT NULL,
    run_id uuid NOT NULL,
    original_message_id text NOT NULL CHECK (length(original_message_id) BETWEEN 1 AND 400),
    replacement_message_id text CHECK (length(replacement_message_id) BETWEEN 1 AND 400),
    attempts smallint NOT NULL CHECK (attempts IN (0, 1)),
    invalid_replacement boolean NOT NULL DEFAULT true,
    cause text NOT NULL CHECK (cause IN ('OUTPUT_LIMIT', 'CONTEXT_TOO_LARGE')),
    status text NOT NULL CHECK (status IN ('recovering', 'succeeded', 'failed')),
    before_budget jsonb NOT NULL CHECK (jsonb_typeof(before_budget) = 'object'),
    after_budget jsonb CHECK (jsonb_typeof(after_budget) = 'object'),
    error_code text,
    created_at timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    PRIMARY KEY (thread_id, original_message_id),
    UNIQUE (thread_id, replacement_message_id),
    FOREIGN KEY (thread_id, run_id) REFERENCES agent.agent_run(thread_id, id) ON DELETE CASCADE,
    CHECK ((attempts = 0 AND replacement_message_id IS NULL AND status = 'failed')
        OR (attempts = 1 AND replacement_message_id IS NOT NULL AND replacement_message_id <> original_message_id)),
    CHECK ((status = 'failed') = (error_code IS NOT NULL)),
    CHECK (status <> 'succeeded' OR after_budget IS NOT NULL)
);
