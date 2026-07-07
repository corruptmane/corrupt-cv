#!/usr/bin/env bash
# End-to-end smoke: submit a generation with the keyless TEST provider and poll
# until the tailored PDF is downloadable. Used by `just smoke` and CI e2e.
set -euo pipefail

BASE="${GATEWAY_BASE:-http://localhost:8080}"

echo "submitting generation to ${BASE} ..."
location=$(curl -fsS -D - -o /dev/null -X POST "${BASE}/generations" \
  --data-urlencode "experience_text=10 years building Go backends and Kubernetes platforms." \
  --data-urlencode "job_description=Platform engineer: k8s, CI/CD, observability, IaC." \
  --data-urlencode "name=Ada Lovelace" \
  --data-urlencode "email=ada@example.com" \
  --data-urlencode "location_city=London" \
  --data-urlencode "location_country=UK" \
  --data-urlencode "provider=test" \
  | tr -d '\r' | awk 'tolower($1) == "location:" { print $2 }')

job_id="${location##*/}"
if [ -z "${job_id}" ]; then
  echo "failed to obtain job id (no redirect Location)"; exit 1
fi
echo "job id: ${job_id}"

for _ in $(seq 1 60); do
  code=$(curl -fsS -o /tmp/smoke_cv.pdf -w '%{http_code}' "${BASE}/generations/${job_id}/pdf" || echo 000)
  if [ "${code}" = "200" ] && head -c4 /tmp/smoke_cv.pdf | grep -q '%PDF'; then
    echo "PDF ready: $(wc -c < /tmp/smoke_cv.pdf) bytes"
    exit 0
  fi
  sleep 2
done

echo "timed out waiting for the PDF"
exit 1
