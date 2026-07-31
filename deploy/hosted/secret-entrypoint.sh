#!/bin/sh
set -eu

load_secret() {
    name="$1"
    eval "path=\${${name}_FILE:-}"
    if [ -n "$path" ]; then
        value="$(sed -n '1p' "$path")"
        if [ -z "$value" ]; then
            echo "empty secret file for $name" >&2
            exit 1
        fi
        export "$name=$value"
        unset "${name}_FILE"
    fi
}

for name in \
    POSTGRES_PASSWORD POSTGRES_PWD \
    JWT_SECRET PGRST_JWT_SECRET ENCRYPTION_KEY APP_ENCRYPTION_KEY \
    ROOT_ADMIN_PASSWORD PGRST_DB_URI DATABASE_URL
do
    load_secret "$name"
done

exec "$@"
