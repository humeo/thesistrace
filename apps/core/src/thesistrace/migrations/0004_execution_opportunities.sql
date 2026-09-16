CREATE SEQUENCE researchers.execution_opportunity_sequence AS bigint;
CREATE TABLE researchers.execution_opportunities (
    pool text NOT NULL CHECK (pool IN ('research', 'batch-research')),
    researcher_id uuid NOT NULL REFERENCES researchers.researchers(id),
    last_sequence bigint NOT NULL CHECK (last_sequence > 0),
    PRIMARY KEY (pool, researcher_id)
);
