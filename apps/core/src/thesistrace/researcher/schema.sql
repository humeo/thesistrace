CREATE SCHEMA researchers;

SET default_tablespace = '';
SET default_table_access_method = heap;

CREATE TABLE researchers.researchers (
    id uuid PRIMARY KEY,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
