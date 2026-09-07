CREATE SCHEMA research_folders;

SET default_tablespace = '';
SET default_table_access_method = heap;

CREATE TABLE research_folders.folders (
    researcher_id uuid NOT NULL,
    id text NOT NULL,
    name text NOT NULL,
    is_default boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT folders_name_check CHECK (name = btrim(name) AND name <> ''),
    CONSTRAINT folders_system_identity_check CHECK (
        (
            id = 'folder_default'
            AND name = 'Default'
            AND is_default
        )
        OR (
            id = 'folder_batch_research'
            AND name = 'Batch Research'
            AND NOT is_default
        )
        OR (
            id <> 'folder_default'
            AND id <> 'folder_batch_research'
            AND NOT is_default
        )
    ),
    PRIMARY KEY (researcher_id, id),
    FOREIGN KEY (researcher_id) REFERENCES researchers.researchers(id)
);

CREATE UNIQUE INDEX research_folders_one_default_idx
ON research_folders.folders (researcher_id)
WHERE is_default;
