--
-- Name: publication; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA publication;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: manifest_objects; Type: TABLE; Schema: publication; Owner: -
--

CREATE TABLE publication.manifest_objects (
    manifest_sha256 text NOT NULL,
    ordinal integer NOT NULL,
    logical_name text NOT NULL,
    object_sha256 text NOT NULL,
    CONSTRAINT manifest_objects_ordinal_check CHECK ((ordinal >= 0))
);


--
-- Name: manifests; Type: TABLE; Schema: publication; Owner: -
--

CREATE TABLE publication.manifests (
    sha256 text NOT NULL,
    schema_version integer NOT NULL,
    kind text NOT NULL,
    manifest_bytes bytea NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT manifests_sha256_check CHECK ((sha256 ~ '^[0-9a-f]{64}$'::text))
);


--
-- Name: objects; Type: TABLE; Schema: publication; Owner: -
--

CREATE TABLE publication.objects (
    sha256 text NOT NULL,
    byte_size bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT objects_byte_size_check CHECK ((byte_size >= 0)),
    CONSTRAINT objects_sha256_check CHECK ((sha256 ~ '^[0-9a-f]{64}$'::text))
);


CREATE TABLE publication.object_deletions (
    object_sha256 text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


CREATE TABLE publication.maintenance_state (
    job text PRIMARY KEY CHECK (job IN ('queued_deletions', 'orphan_scan', 'holding_expiry')),
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

INSERT INTO publication.maintenance_state (job) VALUES ('queued_deletions'), ('orphan_scan'), ('holding_expiry');


--
-- Name: manifest_objects manifest_objects_manifest_sha256_logical_name_key; Type: CONSTRAINT; Schema: publication; Owner: -
--

ALTER TABLE ONLY publication.manifest_objects
    ADD CONSTRAINT manifest_objects_manifest_sha256_logical_name_key UNIQUE (manifest_sha256, logical_name);


--
-- Name: manifest_objects manifest_objects_pkey; Type: CONSTRAINT; Schema: publication; Owner: -
--

ALTER TABLE ONLY publication.manifest_objects
    ADD CONSTRAINT manifest_objects_pkey PRIMARY KEY (manifest_sha256, ordinal);


--
-- Name: manifests manifests_pkey; Type: CONSTRAINT; Schema: publication; Owner: -
--

ALTER TABLE ONLY publication.manifests
    ADD CONSTRAINT manifests_pkey PRIMARY KEY (sha256);


--
-- Name: objects objects_pkey; Type: CONSTRAINT; Schema: publication; Owner: -
--

ALTER TABLE ONLY publication.objects
    ADD CONSTRAINT objects_pkey PRIMARY KEY (sha256);


ALTER TABLE ONLY publication.object_deletions
    ADD CONSTRAINT object_deletions_pkey PRIMARY KEY (object_sha256);


--
-- Name: manifest_objects manifest_objects_manifest_sha256_fkey; Type: FK CONSTRAINT; Schema: publication; Owner: -
--

ALTER TABLE ONLY publication.manifest_objects
    ADD CONSTRAINT manifest_objects_manifest_sha256_fkey FOREIGN KEY (manifest_sha256) REFERENCES publication.manifests(sha256);


--
-- Name: manifest_objects manifest_objects_object_sha256_fkey; Type: FK CONSTRAINT; Schema: publication; Owner: -
--

ALTER TABLE ONLY publication.manifest_objects
    ADD CONSTRAINT manifest_objects_object_sha256_fkey FOREIGN KEY (object_sha256) REFERENCES publication.objects(sha256);


ALTER TABLE ONLY publication.object_deletions
    ADD CONSTRAINT object_deletions_object_sha256_fkey FOREIGN KEY (object_sha256) REFERENCES publication.objects(sha256) ON DELETE CASCADE;

-- Temporary Daily Holding Observation ownership is independent of Result manifests.
CREATE TABLE publication.holding_units (
    id text PRIMARY KEY,
    researcher_id uuid NOT NULL,
    source_kind text NOT NULL CHECK (source_kind IN ('research_run', 'daily_track')),
    source_id text NOT NULL,
    first_session date NOT NULL,
    last_session date NOT NULL CHECK (last_session >= first_session),
    manifest_sha256 text REFERENCES publication.manifests(sha256),
    provenance jsonb NOT NULL CHECK (jsonb_typeof(provenance) = 'object'),
    published_at timestamptz NOT NULL,
    last_read_at timestamptz,
    expires_at timestamptz NOT NULL,
    expired_at timestamptz,
    CHECK (expires_at >= published_at),
    CHECK ((expired_at IS NULL) = (manifest_sha256 IS NOT NULL))
);
CREATE INDEX holding_units_source ON publication.holding_units
    (researcher_id, source_kind, source_id, first_session, id);
CREATE INDEX holding_units_expiry ON publication.holding_units (expires_at, id)
    WHERE expired_at IS NULL;
