CREATE TABLE IF NOT EXISTS thesistrace_control.stored_objects (
    object_key text PRIMARY KEY CHECK (object_key <> ''),
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    compressed_bytes bigint NOT NULL CHECK (compressed_bytes >= 0),
    object_kind text NOT NULL
        CHECK (object_kind IN ('content', 'manifest')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS thesistrace_control.storage_references (
    owner_scope text NOT NULL
        CHECK (owner_scope IN ('workspace', 'platform')),
    workspace_id text,
    resource_kind text NOT NULL CHECK (resource_kind <> ''),
    resource_id text NOT NULL CHECK (resource_id <> ''),
    object_key text NOT NULL
        REFERENCES thesistrace_control.stored_objects(object_key),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (
        (owner_scope = 'workspace' AND workspace_id IS NOT NULL)
        OR (owner_scope = 'platform' AND workspace_id IS NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS storage_reference_identity
ON thesistrace_control.storage_references (
    owner_scope,
    COALESCE(workspace_id, ''),
    resource_kind,
    resource_id,
    object_key
);

CREATE INDEX IF NOT EXISTS workspace_storage_reference_objects
ON thesistrace_control.storage_references (workspace_id, object_key)
WHERE owner_scope = 'workspace';

REVOKE ALL ON thesistrace_control.stored_objects FROM PUBLIC;
REVOKE ALL ON thesistrace_control.storage_references FROM PUBLIC;
REVOKE ALL ON thesistrace_control.stored_objects
FROM thesistrace_api, thesistrace_compute, thesistrace_data;
REVOKE ALL ON thesistrace_control.storage_references
FROM thesistrace_api, thesistrace_compute, thesistrace_data;

CREATE OR REPLACE FUNCTION
thesistrace_control.validated_storage_objects(p_objects jsonb)
RETURNS TABLE (
    object_key text,
    sha256 text,
    compressed_bytes bigint,
    object_kind text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, thesistrace_control
AS $$
BEGIN
    IF p_objects IS NULL
       OR jsonb_typeof(p_objects) <> 'array'
       OR jsonb_array_length(p_objects) = 0 THEN
        RAISE EXCEPTION 'Storage reference request is invalid';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(p_objects) AS item
        WHERE jsonb_typeof(item) <> 'object'
           OR item ->> 'object_key' IS NULL
           OR item ->> 'sha256' IS NULL
           OR item -> 'bytes' IS NULL
           OR item ->> 'kind' IS NULL
           OR item ->> 'sha256' !~ '^[0-9a-f]{64}$'
           OR jsonb_typeof(item -> 'bytes') <> 'number'
           OR item ->> 'bytes' !~ '^(0|[1-9][0-9]*)$'
           OR item ->> 'kind' NOT IN ('content', 'manifest')
           OR (
                item ->> 'kind' = 'content'
                AND item ->> 'object_key'
                    <> 'sha256:' || (item ->> 'sha256')
           )
           OR (
                item ->> 'kind' = 'manifest'
                AND item ->> 'object_key' !~ '^manifest:[^/]+$'
           )
    ) THEN
        RAISE EXCEPTION 'Storage reference object is invalid';
    END IF;
    IF EXISTS (
        SELECT item ->> 'object_key'
        FROM jsonb_array_elements(p_objects) AS item
        GROUP BY item ->> 'object_key'
        HAVING count(DISTINCT jsonb_build_array(
            item ->> 'sha256',
            item ->> 'bytes',
            item ->> 'kind'
        )) > 1
    ) THEN
        RAISE EXCEPTION 'Storage request has conflicting object identities';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(p_objects) AS item
        JOIN thesistrace_control.stored_objects AS stored
          ON stored.object_key = item ->> 'object_key'
        WHERE stored.sha256 <> item ->> 'sha256'
           OR stored.compressed_bytes <> (item ->> 'bytes')::bigint
           OR stored.object_kind <> item ->> 'kind'
    ) THEN
        RAISE EXCEPTION 'Stored object identity conflicts with byte accounting';
    END IF;

    RETURN QUERY
    SELECT DISTINCT
        item ->> 'object_key',
        item ->> 'sha256',
        (item ->> 'bytes')::bigint,
        item ->> 'kind'
    FROM jsonb_array_elements(p_objects) AS item;
END;
$$;

CREATE OR REPLACE FUNCTION
thesistrace_control.ensure_storage_objects(p_objects jsonb)
RETURNS void
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, thesistrace_control
AS $$
    INSERT INTO thesistrace_control.stored_objects (
        object_key,
        sha256,
        compressed_bytes,
        object_kind
    )
    SELECT
        object_value.object_key,
        object_value.sha256,
        object_value.compressed_bytes,
        object_value.object_kind
    FROM thesistrace_control.validated_storage_objects(
        p_objects
    ) AS object_value
    ON CONFLICT (object_key) DO NOTHING;
$$;

REVOKE ALL ON FUNCTION
thesistrace_control.validated_storage_objects(jsonb)
FROM PUBLIC, thesistrace_api, thesistrace_compute, thesistrace_data;
REVOKE ALL ON FUNCTION
thesistrace_control.ensure_storage_objects(jsonb)
FROM PUBLIC, thesistrace_api, thesistrace_compute, thesistrace_data;

CREATE OR REPLACE FUNCTION
thesistrace_control.commit_workspace_storage_references(
    p_resource_kind text,
    p_resource_id text,
    p_objects jsonb
)
RETURNS TABLE (
    accepted boolean,
    used_bytes bigint,
    limit_bytes bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, thesistrace_control
AS $$
DECLARE
    v_workspace_id text;
    v_limit bigint;
    v_used bigint;
    v_growth bigint;
BEGIN
    v_workspace_id := thesistrace_control.current_workspace_id();
    IF v_workspace_id IS NULL THEN
        RAISE EXCEPTION 'Personal Workspace context is missing';
    END IF;
    IF p_resource_kind IS NULL OR p_resource_kind = ''
       OR p_resource_id IS NULL OR p_resource_id = '' THEN
        RAISE EXCEPTION 'Storage reference request is invalid';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended(v_workspace_id || ':private-storage', 0)
    );
    SELECT max_private_storage_bytes
    INTO v_limit
    FROM thesistrace_control.workspace_quota_profiles
    WHERE workspace_id = v_workspace_id
    FOR UPDATE;
    IF v_limit IS NULL THEN
        RAISE EXCEPTION 'Personal Workspace Quota Profile is missing';
    END IF;
    SELECT COALESCE(sum(object_value.compressed_bytes), 0)
    INTO v_growth
    FROM thesistrace_control.validated_storage_objects(
        p_objects
    ) AS object_value
    WHERE NOT EXISTS (
        SELECT 1
        FROM thesistrace_control.storage_references AS reference
        WHERE reference.owner_scope = 'workspace'
          AND reference.workspace_id = v_workspace_id
          AND reference.object_key = object_value.object_key
    );

    SELECT COALESCE(sum(object_value.compressed_bytes), 0)
    INTO v_used
    FROM thesistrace_control.stored_objects AS object_value
    WHERE EXISTS (
        SELECT 1
        FROM thesistrace_control.storage_references AS reference
        WHERE reference.owner_scope = 'workspace'
          AND reference.workspace_id = v_workspace_id
          AND reference.object_key = object_value.object_key
    );

    IF v_used + v_growth > v_limit THEN
        RETURN QUERY SELECT false, v_used, v_limit;
        RETURN;
    END IF;

    PERFORM thesistrace_control.ensure_storage_objects(p_objects);

    INSERT INTO thesistrace_control.storage_references (
        owner_scope,
        workspace_id,
        resource_kind,
        resource_id,
        object_key
    )
    SELECT
        'workspace',
        v_workspace_id,
        p_resource_kind,
        p_resource_id,
        object_value.object_key
    FROM thesistrace_control.validated_storage_objects(
        p_objects
    ) AS object_value
    ON CONFLICT DO NOTHING;

    RETURN QUERY SELECT true, v_used + v_growth, v_limit;
END;
$$;

CREATE OR REPLACE FUNCTION
thesistrace_control.commit_platform_storage_references(
    p_resource_kind text,
    p_resource_id text,
    p_objects jsonb
)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, thesistrace_control
AS $$
DECLARE
    v_bytes bigint;
BEGIN
    IF p_resource_kind IS NULL OR p_resource_kind = ''
       OR p_resource_id IS NULL OR p_resource_id = '' THEN
        RAISE EXCEPTION 'Storage reference request is invalid';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'platform-storage:' || p_resource_kind || ':' || p_resource_id,
            0
        )
    );
    PERFORM thesistrace_control.ensure_storage_objects(p_objects);

    INSERT INTO thesistrace_control.storage_references (
        owner_scope,
        workspace_id,
        resource_kind,
        resource_id,
        object_key
    )
    SELECT
        'platform',
        NULL,
        p_resource_kind,
        p_resource_id,
        object_value.object_key
    FROM thesistrace_control.validated_storage_objects(
        p_objects
    ) AS object_value
    ON CONFLICT DO NOTHING;

    SELECT COALESCE(sum(object_value.compressed_bytes), 0)
    INTO v_bytes
    FROM thesistrace_control.stored_objects AS object_value
    WHERE EXISTS (
        SELECT 1
        FROM thesistrace_control.storage_references AS reference
        WHERE reference.owner_scope = 'platform'
          AND reference.resource_kind = p_resource_kind
          AND reference.resource_id = p_resource_id
          AND reference.object_key = object_value.object_key
    );
    RETURN v_bytes;
END;
$$;

REVOKE ALL ON FUNCTION
thesistrace_control.commit_workspace_storage_references(text, text, jsonb)
FROM PUBLIC;
REVOKE ALL ON FUNCTION
thesistrace_control.commit_platform_storage_references(text, text, jsonb)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
thesistrace_control.commit_workspace_storage_references(text, text, jsonb)
TO thesistrace_api, thesistrace_compute;
GRANT EXECUTE ON FUNCTION
thesistrace_control.commit_platform_storage_references(text, text, jsonb)
TO thesistrace_data;
