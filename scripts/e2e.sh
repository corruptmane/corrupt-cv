#!/usr/bin/env bash
# End-to-end smoke test against a running compose stack (just up).
# Uses the fake/canned-cv model so no API key is needed.
set -euo pipefail

BASE="${BASE:-http://localhost:8080}"
COMPOSE_FILE="deploy/compose/compose.yaml"
COOKIES="$(mktemp /tmp/cvgen-cookies.XXXXXX)"
PDF="$(mktemp /tmp/cvgen-download.XXXXXX.pdf)"
trap 'rm -f "$COOKIES" "$PDF"' EXIT

started_at=$(date +%s)

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

step() {
    echo "==> $*"
}

elapsed() {
    echo "$(($(date +%s) - started_at))s"
}

CAREER_TEXT='Backend engineer with 8 years of experience building distributed systems.
2018-2020: Junior/Mid engineer at Fintech startup PayFlow (Kyiv).
Built payment reconciliation pipelines in Python, moved batch jobs to Celery.
Introduced integration testing and cut regression incidents roughly in half.
2020-2022: Backend engineer at DataMesh Labs.
Owned a Go ingestion service handling ~40k events/sec over Kafka.
Designed idempotent consumers and exactly-once sink semantics into ClickHouse.
Led migration from a monolith to six services with gRPC contracts.
2022-2025: Senior backend engineer at CloudNorth.
Ran the internal platform team: Kubernetes, Helm, ArgoCD, Terraform on AWS.
Built a multi-tenant job scheduler in Go with Postgres and NATS JetStream.
Reduced p99 API latency from 900ms to 120ms via caching and query rewrites.
Mentored four engineers; ran architecture reviews and incident postmortems.
Comfortable with Go, Python, Postgres, NATS, Kafka, Kubernetes, Terraform.
Looking for staff/platform roles with strong infrastructure ownership.'

JOB_DESCRIPTION='We are hiring a Senior Platform Engineer to own our internal developer
platform. You will design and operate Kubernetes-based infrastructure,
build golden-path deployment tooling, and improve observability across
40+ microservices. Requirements: strong Go or Python, deep Postgres and
messaging experience (Kafka/NATS), infrastructure-as-code (Terraform),
and a track record of mentoring engineers. Nice to have: GitOps (Flux or
ArgoCD), progressive delivery, and experience running incident response.'

# --- 1. Get a session cookie -------------------------------------------------
step "GET / (session cookie)"
curl -fsS -c "$COOKIES" -o /dev/null "$BASE/" || fail "GET / failed — is the stack up? (just up)"

# --- 2. Create profile -------------------------------------------------------
step "POST /profile"
curl -fsS -b "$COOKIES" -c "$COOKIES" -o /dev/null "$BASE/profile" \
    --data-urlencode "name=Danylo Marchenko" \
    --data-urlencode "email=danylo.marchenko@example.com" \
    --data-urlencode "city=Kyiv" \
    --data-urlencode "country=Ukraine" \
    --data-urlencode "links=https://github.com/dmarchenko https://linkedin.com/in/dmarchenko" \
    --data-urlencode "career_text=$CAREER_TEXT" \
    || fail "POST /profile failed"

# --- 3. Create job (fake model, NO api key) ----------------------------------
step "POST /jobs (model_key=fake/canned-cv, no api_key)"
headers="$(curl -sS -i -b "$COOKIES" -c "$COOKIES" -o /dev/stdout "$BASE/jobs" \
    --data-urlencode "job_description=$JOB_DESCRIPTION" \
    --data-urlencode "model_key=fake/canned-cv")" || fail "POST /jobs failed"

location="$(printf '%s' "$headers" | tr -d '\r' | awk 'tolower($1)=="location:" {print $2; exit}')"
[ -n "$location" ] || fail "POST /jobs returned no Location header; response was: $headers"
job_id="$(basename "$location")"
[ -n "$job_id" ] || fail "could not extract job id from Location: $location"
echo "    job_id=$job_id"

# --- 4. Poll until completed -------------------------------------------------
step "polling GET /api/jobs/$job_id (up to 90s)"
status=""
poll_started=$(date +%s)
while true; do
    body="$(curl -fsS -b "$COOKIES" "$BASE/api/jobs/$job_id")" || fail "GET /api/jobs/$job_id failed"
    status="$(printf '%s' "$body" | grep -o '"status"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"\([^"]*\)"$/\1/')"
    case "$status" in
        completed)
            echo "    completed after $(($(date +%s) - poll_started))s"
            break
            ;;
        failed)
            fail "job failed; response: $body"
            ;;
    esac
    if [ $(($(date +%s) - poll_started)) -ge 90 ]; then
        fail "job did not complete within 90s (last status: ${status:-unknown}); response: $body"
    fi
    sleep 2
done

# --- 5. Download the PDF -----------------------------------------------------
step "GET /jobs/$job_id/download"
curl -fsSL -b "$COOKIES" -o "$PDF" "$BASE/jobs/$job_id/download" || fail "download failed"

magic="$(head -c 4 "$PDF")"
[ "$magic" = "%PDF" ] || fail "downloaded file is not a PDF (first bytes: $magic)"
size="$(wc -c < "$PDF" | tr -d ' ')"
[ "$size" -gt 10240 ] || fail "PDF suspiciously small: ${size} bytes (expected > 10240)"
echo "    PDF ok: ${size} bytes"

# --- 6. Assert API key was consumed from Valkey ------------------------------
step "checking cv:apikey:$job_id is gone from valkey"
exists="$(docker compose -f "$COMPOSE_FILE" exec -T valkey valkey-cli EXISTS "cv:apikey:$job_id" | tr -d '[:space:]')"
[ "$exists" = "0" ] || fail "cv:apikey:$job_id still present in valkey (EXISTS=$exists)"

echo
echo "PASS: full pipeline in $(elapsed) (job $job_id, ${size}-byte PDF, api key absent from valkey)"
