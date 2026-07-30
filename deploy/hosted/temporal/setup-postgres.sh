#!/bin/sh
set -eu

: "${POSTGRES_SEEDS:?POSTGRES_SEEDS is required}"
: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_PWD:?POSTGRES_PWD is required}"

setup_database() {
    database="$1"
    schema_path="$2"
    if temporal-sql-tool \
        --plugin postgres12 \
        --ep "$POSTGRES_SEEDS" \
        -u "$POSTGRES_USER" \
        -p "${DB_PORT:-5432}" \
        --db "$database" \
        read-schema-version >/dev/null 2>&1; then
        echo "$database schema already exists"
    else
        temporal-sql-tool \
            --plugin postgres12 \
            --ep "$POSTGRES_SEEDS" \
            -u "$POSTGRES_USER" \
            -p "${DB_PORT:-5432}" \
            --db "$database" create
        temporal-sql-tool \
            --plugin postgres12 \
            --ep "$POSTGRES_SEEDS" \
            -u "$POSTGRES_USER" \
            -p "${DB_PORT:-5432}" \
            --db "$database" setup-schema -v 0.0
    fi
    temporal-sql-tool \
        --plugin postgres12 \
        --ep "$POSTGRES_SEEDS" \
        -u "$POSTGRES_USER" \
        -p "${DB_PORT:-5432}" \
        --db "$database" update-schema -d "$schema_path"
}

export SQL_PASSWORD="$POSTGRES_PWD"
setup_database temporal /etc/temporal/schema/postgresql/v12/temporal/versioned
setup_database temporal_visibility /etc/temporal/schema/postgresql/v12/visibility/versioned
