--
-- Name: definitions; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA definitions;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: records; Type: TABLE; Schema: definitions; Owner: -
--

CREATE TABLE definitions.records (
    id text NOT NULL,
    revision integer NOT NULL,
    content jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT records_content_check CHECK ((jsonb_typeof(content) = 'object'::text)),
    CONSTRAINT records_revision_check CHECK ((revision > 0))
);


--
-- Name: run_receipts; Type: TABLE; Schema: definitions; Owner: -
--

CREATE TABLE definitions.run_receipts (
    request_id text NOT NULL,
    request_fingerprint text NOT NULL,
    definition_id text NOT NULL,
    saved_revision integer NOT NULL,
    saved_content jsonb NOT NULL,
    outcome text NOT NULL,
    issues jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    research_run_id text,
    CONSTRAINT run_receipts_admission_shape_check CHECK ((((outcome = 'rejected'::text) AND (research_run_id IS NULL)) OR ((outcome = 'accepted'::text) AND (research_run_id IS NOT NULL) AND (issues = '[]'::jsonb)))),
    CONSTRAINT run_receipts_issues_check CHECK ((jsonb_typeof(issues) = 'array'::text)),
    CONSTRAINT run_receipts_outcome_check CHECK ((outcome = ANY (ARRAY['rejected'::text, 'accepted'::text]))),
    CONSTRAINT run_receipts_saved_content_check CHECK ((jsonb_typeof(saved_content) = 'object'::text)),
    CONSTRAINT run_receipts_saved_revision_check CHECK ((saved_revision > 0))
);


--
-- Name: records records_pkey; Type: CONSTRAINT; Schema: definitions; Owner: -
--

ALTER TABLE ONLY definitions.records
    ADD CONSTRAINT records_pkey PRIMARY KEY (id);


--
-- Name: run_receipts run_receipts_pkey; Type: CONSTRAINT; Schema: definitions; Owner: -
--

ALTER TABLE ONLY definitions.run_receipts
    ADD CONSTRAINT run_receipts_pkey PRIMARY KEY (request_id);


--
-- Name: definitions_records_updated_idx; Type: INDEX; Schema: definitions; Owner: -
--

CREATE INDEX definitions_records_updated_idx ON definitions.records USING btree (updated_at DESC, id);


--
-- Name: run_receipts run_receipts_definition_id_fkey; Type: FK CONSTRAINT; Schema: definitions; Owner: -
--

ALTER TABLE ONLY definitions.run_receipts
    ADD CONSTRAINT run_receipts_definition_id_fkey FOREIGN KEY (definition_id) REFERENCES definitions.records(id);
