CREATE SCHEMA research_agent;

CREATE TABLE research_agent.cursor_secrets (
    singleton smallint PRIMARY KEY CHECK (singleton = 1),
    secret text DEFAULT (
        replace(gen_random_uuid()::text, '-', '')
        || replace(gen_random_uuid()::text, '-', '')
    ) NOT NULL CHECK (secret ~ '^[0-9a-f]{64}$')
);

INSERT INTO research_agent.cursor_secrets (singleton) VALUES (1);
