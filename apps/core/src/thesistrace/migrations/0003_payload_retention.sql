-- Diagnostic payload lifetime is independent of its immutable reporting manifest.
CREATE TABLE publication.payload_retention (
    manifest_sha256 text PRIMARY KEY REFERENCES publication.manifests(sha256) ON DELETE CASCADE,
    payload_names text[] NOT NULL CHECK (cardinality(payload_names) > 0),
    published_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    last_read_at timestamptz,
    expires_at timestamptz NOT NULL DEFAULT (clock_timestamp() + interval '7 days'),
    expired_at timestamptz,
    CHECK (expires_at >= published_at)
);
CREATE INDEX payload_retention_expiry ON publication.payload_retention(expires_at, manifest_sha256)
    WHERE expired_at IS NULL;

CREATE TABLE publication.expired_payloads (
    manifest_sha256 text NOT NULL REFERENCES publication.payload_retention(manifest_sha256) ON DELETE CASCADE,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    logical_name text NOT NULL,
    object_sha256 text NOT NULL CHECK (object_sha256 ~ '^[0-9a-f]{64}$'),
    byte_size bigint NOT NULL CHECK (byte_size >= 0),
    PRIMARY KEY (manifest_sha256, ordinal),
    UNIQUE (manifest_sha256, logical_name)
);
