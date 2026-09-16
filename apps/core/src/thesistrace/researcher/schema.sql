CREATE SCHEMA researchers;

SET default_tablespace = '';
SET default_table_access_method = heap;

CREATE TABLE researchers.researchers (
    id uuid PRIMARY KEY,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE SEQUENCE researchers.execution_opportunity_sequence AS bigint;

CREATE TABLE researchers.execution_opportunities (
    pool text NOT NULL CHECK (pool IN ('research', 'batch-research')),
    researcher_id uuid NOT NULL REFERENCES researchers.researchers(id),
    last_sequence bigint NOT NULL CHECK (last_sequence > 0),
    PRIMARY KEY (pool, researcher_id)
);
