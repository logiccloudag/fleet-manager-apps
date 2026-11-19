#!/bin/bash
# Maps InfluxDB 1.x (v1) databases to buckets (DBRP mappings), so InfluxQL
# clients such as a Grafana data source with query language InfluxQL can
# read a bucket under another database name. InfluxDB 2.4 and later already
# map every bucket to the database of the same name (virtual mappings), so
# that case needs no entry. Runs as the Job <release>-v1-databases-<revision>
# (Helm) and in the background after each start (compose).
#
# INFLUXDB_V1_DATABASES: comma separated entries "bucket:database". A
# missing bucket is created with the retention INFLUXDB_V1_RETENTION.
# Existing mappings are kept. The influx CLI reads INFLUX_HOST, INFLUX_TOKEN
# and INFLUX_ORG from the environment.
set -euo pipefail
name='^[A-Za-z0-9._-]+$'
entries=()
IFS=, read -ra raw <<<"${INFLUXDB_V1_DATABASES}"
for entry in "${raw[@]}"; do
  entry="${entry//[[:space:]]/}"
  [ -n "${entry}" ] || continue
  bucket="${entry%%:*}"
  database="${entry#*:}"
  if [[ "${entry}" != *:* ]] || ! [[ "${bucket}" =~ ${name} && "${database}" =~ ${name} ]]; then
    echo "ERROR: v1 database entry '${entry}' must be bucket:database (letters, digits, '.', '_', '-')" >&2
    exit 1
  fi
  entries+=("${bucket}:${database}")
done
for _ in $(seq 1 60); do
  influx bucket list --hide-headers >/dev/null 2>&1 && break
  sleep 5
done
if ! influx bucket list --hide-headers >/dev/null; then
  echo "ERROR: InfluxDB at ${INFLUX_HOST} does not answer with the operator token" >&2
  exit 1
fi
for entry in "${entries[@]}"; do
  bucket="${entry%%:*}"
  database="${entry#*:}"
  # Only the real mappings count: the CLI lists the virtual ones after them.
  if influx v1 dbrp list --db "${database}" --json | sed '/VIRTUAL DBRP MAPPINGS/,$d' | grep -q '"database"'; then
    echo "v1 database ${database} is already mapped"
    continue
  fi
  id="$(influx bucket list --name "${bucket}" --hide-headers 2>/dev/null | awk 'NR == 1 { print $1 }' || true)"
  if [ -z "${id}" ]; then
    id="$(influx bucket create --name "${bucket}" --retention "${INFLUXDB_V1_RETENTION}" --hide-headers | awk 'NR == 1 { print $1 }')"
    echo "Created bucket ${bucket} (retention ${INFLUXDB_V1_RETENTION})"
  fi
  influx v1 dbrp create --bucket-id "${id}" --db "${database}" --rp autogen --default --hide-headers >/dev/null
  echo "Mapped v1 database ${database} (retention policy autogen) to bucket ${bucket}"
done
