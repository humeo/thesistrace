#!/bin/sh
set -eu

address="${TEMPORAL_ADDRESS:-temporal:7233}"
namespace="${TEMPORAL_NAMESPACE:-thesistrace}"
attempt=1

until temporal operator cluster health --address "$address"; do
    if [ "$attempt" -ge 60 ]; then
        echo "Temporal did not become healthy" >&2
        exit 1
    fi
    attempt=$((attempt + 1))
    sleep 2
done

if temporal operator namespace describe --address "$address" --namespace "$namespace" \
    >/dev/null 2>&1; then
    echo "Temporal namespace already exists: $namespace"
else
    temporal operator namespace create \
        --address "$address" \
        --namespace "$namespace" \
        --retention 7d
fi
