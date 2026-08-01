#!/bin/sh
set -eu

address="${TEMPORAL_ADDRESS:-temporal:7233}"
namespace="${TEMPORAL_NAMESPACE:-thesistrace}"
attempt=1

while [ "$attempt" -le 60 ]; do
    if ! temporal operator cluster health --address "$address"; then
        :
    elif temporal operator namespace describe --address "$address" --namespace "$namespace" \
        >/dev/null 2>&1; then
        echo "Temporal namespace already exists: $namespace"
        exit 0
    elif temporal operator namespace create \
        --address "$address" \
        --namespace "$namespace" \
        --retention 7d; then
        exit 0
    fi

    if [ "$attempt" -ge 60 ]; then
        break
    fi
    attempt=$((attempt + 1))
    sleep 2
done

echo "Temporal namespace did not become available" >&2
exit 1
