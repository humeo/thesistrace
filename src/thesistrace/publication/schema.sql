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
