CREATE SCHEMA research_folders;

SET default_tablespace = '';
SET default_table_access_method = heap;

CREATE TABLE research_folders.folders (
    id text PRIMARY KEY,
    name text NOT NULL,
    is_default boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT folders_name_check CHECK (name = btrim(name) AND name <> ''),
    CONSTRAINT folders_default_identity_check CHECK (
        NOT is_default OR (id = 'folder_default' AND name = 'Default')
    )
);

CREATE UNIQUE INDEX research_folders_one_default_idx
ON research_folders.folders (is_default)
WHERE is_default;

INSERT INTO research_folders.folders (id, name, is_default)
VALUES ('folder_default', 'Default', true);

INSERT INTO research_folders.folders (id, name, is_default)
VALUES ('folder_batch_research', 'Batch Research', false);
