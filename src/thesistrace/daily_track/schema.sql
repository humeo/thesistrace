--
-- Name: daily_tracks; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA daily_tracks;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: retry_receipts; Type: TABLE; Schema: daily_tracks; Owner: -
--

CREATE TABLE daily_tracks.retry_receipts (
    request_id text NOT NULL,
    request_fingerprint text NOT NULL,
    track_id text NOT NULL,
    outcome jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    progression_id text NOT NULL,
    CONSTRAINT retry_receipts_outcome_check CHECK ((jsonb_typeof(outcome) = 'object'::text))
);


--
-- Name: session_checkpoints; Type: TABLE; Schema: daily_tracks; Owner: -
--

CREATE TABLE daily_tracks.session_checkpoints (
    manifest_sha256 text NOT NULL,
    track_id text NOT NULL,
    progression_id text,
    predecessor_manifest_sha256 text,
    boundary_session date NOT NULL,
    terminal_strategy_state jsonb NOT NULL,
    data_generation_id text NOT NULL,
    provenance jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT session_checkpoints_check CHECK ((((progression_id IS NULL) AND (predecessor_manifest_sha256 IS NULL)) OR ((progression_id IS NOT NULL) AND (predecessor_manifest_sha256 IS NOT NULL)))),
    CONSTRAINT session_checkpoints_provenance_check CHECK ((jsonb_typeof(provenance) = 'object'::text)),
    CONSTRAINT session_checkpoints_terminal_strategy_state_check CHECK ((jsonb_typeof(terminal_strategy_state) = 'object'::text))
);


--
-- Name: session_progression_attempts; Type: TABLE; Schema: daily_tracks; Owner: -
--

CREATE TABLE daily_tracks.session_progression_attempts (
    id text NOT NULL,
    progression_id text NOT NULL,
    track_id text NOT NULL,
    ordinal integer NOT NULL,
    fence bigint NOT NULL,
    generation_pin_id text NOT NULL,
    data_generation_id text NOT NULL,
    data_through_session date NOT NULL,
    status text NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    heartbeat_at timestamp with time zone DEFAULT now() NOT NULL,
    lease_expires_at timestamp with time zone NOT NULL,
    finished_at timestamp with time zone,
    failure_reason text,
    CONSTRAINT session_progression_attempts_fence_check CHECK ((fence > 0)),
    CONSTRAINT session_progression_attempts_ordinal_check CHECK ((ordinal > 0)),
    CONSTRAINT session_progression_attempts_status_check CHECK ((status = ANY (ARRAY['running'::text, 'succeeded'::text, 'failed'::text, 'cancelled'::text])))
);


--
-- Name: session_progressions; Type: TABLE; Schema: daily_tracks; Owner: -
--

CREATE TABLE daily_tracks.session_progressions (
    id text NOT NULL,
    track_id text NOT NULL,
    predecessor_checkpoint_manifest_sha256 text NOT NULL,
    target_sessions date[] NOT NULL,
    target_start_session date NOT NULL,
    target_end_session date NOT NULL,
    data_generation_id text NOT NULL,
    status text NOT NULL,
    checkpoint_manifest_sha256 text,
    provenance jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    CONSTRAINT session_progressions_check CHECK ((target_start_session = target_sessions[1])),
    CONSTRAINT session_progressions_check1 CHECK ((target_end_session = target_sessions[cardinality(target_sessions)])),
    CONSTRAINT session_progressions_check2 CHECK ((((status = 'succeeded'::text) AND (checkpoint_manifest_sha256 IS NOT NULL) AND (finished_at IS NOT NULL)) OR ((status <> 'succeeded'::text) AND (checkpoint_manifest_sha256 IS NULL)))),
    CONSTRAINT session_progressions_provenance_check CHECK ((jsonb_typeof(provenance) = 'object'::text)),
    CONSTRAINT session_progressions_status_check CHECK ((status = ANY (ARRAY['running'::text, 'succeeded'::text, 'blocked'::text, 'cancelled'::text]))),
    CONSTRAINT session_progressions_target_sessions_check CHECK ((cardinality(target_sessions) > 0))
);


--
-- Name: session_tracking_states; Type: TABLE; Schema: daily_tracks; Owner: -
--

CREATE TABLE daily_tracks.session_tracking_states (
    track_id text NOT NULL,
    origin_session date NOT NULL,
    origin_checkpoint_manifest_sha256 text NOT NULL,
    current_checkpoint_manifest_sha256 text NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: stop_receipts; Type: TABLE; Schema: daily_tracks; Owner: -
--

CREATE TABLE daily_tracks.stop_receipts (
    request_id text NOT NULL,
    request_fingerprint text NOT NULL,
    track_id text NOT NULL,
    outcome jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT stop_receipts_outcome_check CHECK ((jsonb_typeof(outcome) = 'object'::text))
);


--
-- Name: tracks; Type: TABLE; Schema: daily_tracks; Owner: -
--

CREATE TABLE daily_tracks.tracks (
    id text NOT NULL,
    status text NOT NULL,
    seed_run_id text NOT NULL,
    origin jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    execution_fence bigint DEFAULT 0 NOT NULL,
    blocked_reason text,
    blocked_progression_id text,
    CONSTRAINT tracks_lifecycle_state_check CHECK ((((status = ANY (ARRAY['active'::text, 'stopped'::text])) AND (blocked_progression_id IS NULL) AND (blocked_reason IS NULL)) OR ((status = 'blocked'::text) AND (blocked_progression_id IS NOT NULL) AND (blocked_reason IS NOT NULL)))),
    CONSTRAINT tracks_origin_check CHECK ((jsonb_typeof(origin) = 'object'::text)),
    CONSTRAINT tracks_status_check CHECK ((status = ANY (ARRAY['active'::text, 'blocked'::text, 'stopped'::text])))
);


--
-- Name: retry_receipts retry_receipts_pkey; Type: CONSTRAINT; Schema: daily_tracks; Owner: -
--

ALTER TABLE ONLY daily_tracks.retry_receipts
    ADD CONSTRAINT retry_receipts_pkey PRIMARY KEY (request_id);


--
-- Name: session_checkpoints session_checkpoints_pkey; Type: CONSTRAINT; Schema: daily_tracks; Owner: -
--

ALTER TABLE ONLY daily_tracks.session_checkpoints
    ADD CONSTRAINT session_checkpoints_pkey PRIMARY KEY (manifest_sha256);


--
-- Name: session_checkpoints session_checkpoints_track_id_boundary_session_key; Type: CONSTRAINT; Schema: daily_tracks; Owner: -
--

ALTER TABLE ONLY daily_tracks.session_checkpoints
    ADD CONSTRAINT session_checkpoints_track_id_boundary_session_key UNIQUE (track_id, boundary_session);


--
-- Name: session_checkpoints session_checkpoints_track_id_boundary_session_manifest_sha2_key; Type: CONSTRAINT; Schema: daily_tracks; Owner: -
--

ALTER TABLE ONLY daily_tracks.session_checkpoints
    ADD CONSTRAINT session_checkpoints_track_id_boundary_session_manifest_sha2_key UNIQUE (track_id, boundary_session, manifest_sha256);


--
-- Name: session_checkpoints session_checkpoints_track_id_manifest_sha256_key; Type: CONSTRAINT; Schema: daily_tracks; Owner: -
--

ALTER TABLE ONLY daily_tracks.session_checkpoints
    ADD CONSTRAINT session_checkpoints_track_id_manifest_sha256_key UNIQUE (track_id, manifest_sha256);


--
-- Name: session_checkpoints session_checkpoints_track_id_progression_id_manifest_sha256_key; Type: CONSTRAINT; Schema: daily_tracks; Owner: -
--

ALTER TABLE ONLY daily_tracks.session_checkpoints
    ADD CONSTRAINT session_checkpoints_track_id_progression_id_manifest_sha256_key UNIQUE (track_id, progression_id, manifest_sha256);


--
-- Name: session_progression_attempts session_progression_attempts_generation_pin_id_key; Type: CONSTRAINT; Schema: daily_tracks; Owner: -
--

ALTER TABLE ONLY daily_tracks.session_progression_attempts
    ADD CONSTRAINT session_progression_attempts_generation_pin_id_key UNIQUE (generation_pin_id);


--
-- Name: session_progression_attempts session_progression_attempts_pkey; Type: CONSTRAINT; Schema: daily_tracks; Owner: -
--

ALTER TABLE ONLY daily_tracks.session_progression_attempts
    ADD CONSTRAINT session_progression_attempts_pkey PRIMARY KEY (id);


--
-- Name: session_progression_attempts session_progression_attempts_progression_id_ordinal_key; Type: CONSTRAINT; Schema: daily_tracks; Owner: -
--

ALTER TABLE ONLY daily_tracks.session_progression_attempts
    ADD CONSTRAINT session_progression_attempts_progression_id_ordinal_key UNIQUE (progression_id, ordinal);


--
-- Name: session_progressions session_progressions_pkey; Type: CONSTRAINT; Schema: daily_tracks; Owner: -
--

ALTER TABLE ONLY daily_tracks.session_progressions
    ADD CONSTRAINT session_progressions_pkey PRIMARY KEY (id);


--
-- Name: session_progressions session_progressions_track_id_id_key; Type: CONSTRAINT; Schema: daily_tracks; Owner: -
--

ALTER TABLE ONLY daily_tracks.session_progressions
    ADD CONSTRAINT session_progressions_track_id_id_key UNIQUE (track_id, id);


--
-- Name: session_progressions session_progressions_track_id_id_target_end_session_key; Type: CONSTRAINT; Schema: daily_tracks; Owner: -
--

ALTER TABLE ONLY daily_tracks.session_progressions
    ADD CONSTRAINT session_progressions_track_id_id_target_end_session_key UNIQUE (track_id, id, target_end_session);


--
-- Name: session_progressions session_progressions_track_id_target_end_session_key; Type: CONSTRAINT; Schema: daily_tracks; Owner: -
--

ALTER TABLE ONLY daily_tracks.session_progressions
    ADD CONSTRAINT session_progressions_track_id_target_end_session_key UNIQUE (track_id, target_end_session);


--
-- Name: session_tracking_states session_tracking_states_pkey; Type: CONSTRAINT; Schema: daily_tracks; Owner: -
--

ALTER TABLE ONLY daily_tracks.session_tracking_states
    ADD CONSTRAINT session_tracking_states_pkey PRIMARY KEY (track_id);


--
-- Name: stop_receipts stop_receipts_pkey; Type: CONSTRAINT; Schema: daily_tracks; Owner: -
--

ALTER TABLE ONLY daily_tracks.stop_receipts
    ADD CONSTRAINT stop_receipts_pkey PRIMARY KEY (request_id);


--
-- Name: tracks tracks_pkey; Type: CONSTRAINT; Schema: daily_tracks; Owner: -
--

ALTER TABLE ONLY daily_tracks.tracks
    ADD CONSTRAINT tracks_pkey PRIMARY KEY (id);


--
-- Name: tracks tracks_seed_run_id_key; Type: CONSTRAINT; Schema: daily_tracks; Owner: -
--

ALTER TABLE ONLY daily_tracks.tracks
    ADD CONSTRAINT tracks_seed_run_id_key UNIQUE (seed_run_id);


--
-- Name: daily_tracks_created_idx; Type: INDEX; Schema: daily_tracks; Owner: -
--

CREATE INDEX daily_tracks_created_idx ON daily_tracks.tracks USING btree (created_at DESC, id);


--
-- Name: daily_tracks_one_live_session_attempt_idx; Type: INDEX; Schema: daily_tracks; Owner: -
--

CREATE UNIQUE INDEX daily_tracks_one_live_session_attempt_idx ON daily_tracks.session_progression_attempts USING btree (progression_id) WHERE (status = 'running'::text);


--
-- Name: daily_tracks_one_unresolved_session_progression_idx; Type: INDEX; Schema: daily_tracks; Owner: -
--

CREATE UNIQUE INDEX daily_tracks_one_unresolved_session_progression_idx ON daily_tracks.session_progressions USING btree (track_id) WHERE (status = ANY (ARRAY['running'::text, 'blocked'::text]));


--
-- Name: retry_receipts retry_receipts_progression_id_fkey; Type: FK CONSTRAINT; Schema: daily_tracks; Owner: -
--

ALTER TABLE ONLY daily_tracks.retry_receipts
    ADD CONSTRAINT retry_receipts_progression_id_fkey FOREIGN KEY (progression_id) REFERENCES daily_tracks.session_progressions(id) ON DELETE CASCADE;


--
-- Name: retry_receipts retry_receipts_track_id_fkey; Type: FK CONSTRAINT; Schema: daily_tracks; Owner: -
--

ALTER TABLE ONLY daily_tracks.retry_receipts
    ADD CONSTRAINT retry_receipts_track_id_fkey FOREIGN KEY (track_id) REFERENCES daily_tracks.tracks(id) ON DELETE CASCADE;


--
-- Name: session_checkpoints session_checkpoint_progression_fk; Type: FK CONSTRAINT; Schema: daily_tracks; Owner: -
--

ALTER TABLE ONLY daily_tracks.session_checkpoints
    ADD CONSTRAINT session_checkpoint_progression_fk FOREIGN KEY (track_id, progression_id, boundary_session) REFERENCES daily_tracks.session_progressions(track_id, id, target_end_session) ON DELETE CASCADE;


--
-- Name: session_checkpoints session_checkpoints_track_id_fkey; Type: FK CONSTRAINT; Schema: daily_tracks; Owner: -
--

ALTER TABLE ONLY daily_tracks.session_checkpoints
    ADD CONSTRAINT session_checkpoints_track_id_fkey FOREIGN KEY (track_id) REFERENCES daily_tracks.tracks(id) ON DELETE CASCADE;


--
-- Name: session_checkpoints session_checkpoints_track_id_predecessor_manifest_sha256_fkey; Type: FK CONSTRAINT; Schema: daily_tracks; Owner: -
--

ALTER TABLE ONLY daily_tracks.session_checkpoints
    ADD CONSTRAINT session_checkpoints_track_id_predecessor_manifest_sha256_fkey FOREIGN KEY (track_id, predecessor_manifest_sha256) REFERENCES daily_tracks.session_checkpoints(track_id, manifest_sha256);


--
-- Name: session_progression_attempts session_progression_attempts_track_id_progression_id_fkey; Type: FK CONSTRAINT; Schema: daily_tracks; Owner: -
--

ALTER TABLE ONLY daily_tracks.session_progression_attempts
    ADD CONSTRAINT session_progression_attempts_track_id_progression_id_fkey FOREIGN KEY (track_id, progression_id) REFERENCES daily_tracks.session_progressions(track_id, id) ON DELETE CASCADE;


--
-- Name: session_progressions session_progression_checkpoint_fk; Type: FK CONSTRAINT; Schema: daily_tracks; Owner: -
--

ALTER TABLE ONLY daily_tracks.session_progressions
    ADD CONSTRAINT session_progression_checkpoint_fk FOREIGN KEY (track_id, id, checkpoint_manifest_sha256) REFERENCES daily_tracks.session_checkpoints(track_id, progression_id, manifest_sha256);


--
-- Name: session_progressions session_progressions_track_id_fkey; Type: FK CONSTRAINT; Schema: daily_tracks; Owner: -
--

ALTER TABLE ONLY daily_tracks.session_progressions
    ADD CONSTRAINT session_progressions_track_id_fkey FOREIGN KEY (track_id) REFERENCES daily_tracks.tracks(id) ON DELETE CASCADE;


--
-- Name: session_progressions session_progressions_track_id_predecessor_checkpoint_manif_fkey; Type: FK CONSTRAINT; Schema: daily_tracks; Owner: -
--

ALTER TABLE ONLY daily_tracks.session_progressions
    ADD CONSTRAINT session_progressions_track_id_predecessor_checkpoint_manif_fkey FOREIGN KEY (track_id, predecessor_checkpoint_manifest_sha256) REFERENCES daily_tracks.session_checkpoints(track_id, manifest_sha256);


--
-- Name: session_tracking_states session_tracking_states_track_id_current_checkpoint_manife_fkey; Type: FK CONSTRAINT; Schema: daily_tracks; Owner: -
--

ALTER TABLE ONLY daily_tracks.session_tracking_states
    ADD CONSTRAINT session_tracking_states_track_id_current_checkpoint_manife_fkey FOREIGN KEY (track_id, current_checkpoint_manifest_sha256) REFERENCES daily_tracks.session_checkpoints(track_id, manifest_sha256);


--
-- Name: session_tracking_states session_tracking_states_track_id_fkey; Type: FK CONSTRAINT; Schema: daily_tracks; Owner: -
--

ALTER TABLE ONLY daily_tracks.session_tracking_states
    ADD CONSTRAINT session_tracking_states_track_id_fkey FOREIGN KEY (track_id) REFERENCES daily_tracks.tracks(id) ON DELETE CASCADE;


--
-- Name: session_tracking_states session_tracking_states_track_id_origin_session_origin_che_fkey; Type: FK CONSTRAINT; Schema: daily_tracks; Owner: -
--

ALTER TABLE ONLY daily_tracks.session_tracking_states
    ADD CONSTRAINT session_tracking_states_track_id_origin_session_origin_che_fkey FOREIGN KEY (track_id, origin_session, origin_checkpoint_manifest_sha256) REFERENCES daily_tracks.session_checkpoints(track_id, boundary_session, manifest_sha256);


--
-- Name: stop_receipts stop_receipts_track_id_fkey; Type: FK CONSTRAINT; Schema: daily_tracks; Owner: -
--

ALTER TABLE ONLY daily_tracks.stop_receipts
    ADD CONSTRAINT stop_receipts_track_id_fkey FOREIGN KEY (track_id) REFERENCES daily_tracks.tracks(id) ON DELETE CASCADE;


--
-- Name: tracks tracks_blocked_progression_id_fkey; Type: FK CONSTRAINT; Schema: daily_tracks; Owner: -
--

ALTER TABLE ONLY daily_tracks.tracks
    ADD CONSTRAINT tracks_blocked_progression_id_fkey FOREIGN KEY (blocked_progression_id) REFERENCES daily_tracks.session_progressions(id);
