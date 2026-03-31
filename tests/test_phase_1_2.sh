#!/usr/bin/env bash
# Phase 1 & 2 — Idempotent Integration Test Script
# Re-run safely: wipes DB via /init check and rebuilds state each run.
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
DOCKER_DIR="${DOCKER_DIR:-$(cd "$(dirname "$0")/../docker" && pwd)}"
PASS=0
FAIL=0
SKIP=0
FAILURES=""

# ── Helpers ──────────────────────────────────────────────────────────────────

green()  { printf "\033[32m%s\033[0m\n" "$*"; }
red()    { printf "\033[31m%s\033[0m\n" "$*"; }
yellow() { printf "\033[33m%s\033[0m\n" "$*"; }
bold()   { printf "\033[1m%s\033[0m\n" "$*"; }

assert_status() {
  local test_id="$1" expected="$2" actual="$3"
  if [ "$actual" -eq "$expected" ]; then
    green "  ✓ $test_id — HTTP $actual (expected $expected)"
    PASS=$((PASS + 1))
  else
    red "  ✗ $test_id — HTTP $actual (expected $expected)"
    FAIL=$((FAIL + 1))
    FAILURES="$FAILURES\n  ✗ $test_id"
  fi
}

assert_status_oneof() {
  local test_id="$1" actual="$2"
  shift 2
  for expected in "$@"; do
    if [ "$actual" -eq "$expected" ]; then
      green "  ✓ $test_id — HTTP $actual (expected one of $*)"
      PASS=$((PASS + 1))
      return
    fi
  done
  red "  ✗ $test_id — HTTP $actual (expected one of $*)"
  FAIL=$((FAIL + 1))
  FAILURES="$FAILURES\n  ✗ $test_id"
}

assert_json_field() {
  local test_id="$1" body="$2" field="$3" expected="$4"
  local actual
  actual=$(echo "$body" | jq -r "$field" 2>/dev/null || echo "__jq_error__")
  if [ "$actual" = "$expected" ]; then
    green "  ✓ $test_id — $field = $expected"
    PASS=$((PASS + 1))
  else
    red "  ✗ $test_id — $field = '$actual' (expected '$expected')"
    FAIL=$((FAIL + 1))
    FAILURES="$FAILURES\n  ✗ $test_id"
  fi
}

assert_json_nonempty() {
  local test_id="$1" body="$2" field="$3"
  local actual
  actual=$(echo "$body" | jq -r "$field" 2>/dev/null || echo "")
  if [ -n "$actual" ] && [ "$actual" != "null" ] && [ "$actual" != "" ]; then
    green "  ✓ $test_id — $field is present"
    PASS=$((PASS + 1))
  else
    red "  ✗ $test_id — $field is empty/null"
    FAIL=$((FAIL + 1))
    FAILURES="$FAILURES\n  ✗ $test_id"
  fi
}

curl_get() {
  local url="$1"; shift
  curl -s -w "\n%{http_code}" "$url" "$@"
}

curl_post() {
  local url="$1" data="$2"; shift 2
  curl -s -w "\n%{http_code}" -X POST "$url" \
    -H "Content-Type: application/json" \
    -d "$data" "$@"
}

parse_response() {
  # Sets BODY and STATUS from curl output (body + status code on last line)
  local raw="$1"
  STATUS=$(echo "$raw" | tail -1)
  BODY=$(echo "$raw" | sed '$d')
}

# ── Wait for server ──────────────────────────────────────────────────────────

bold "⏳ Waiting for server at $BASE_URL ..."
for i in $(seq 1 30); do
  if curl -sf "$BASE_URL/health" > /dev/null 2>&1; then
    green "Server is up!"
    break
  fi
  if [ "$i" -eq 30 ]; then
    red "Server not reachable after 30s. Aborting."
    exit 1
  fi
  sleep 1
done

# ══════════════════════════════════════════════════════════════════════════════
bold ""
bold "═══ Phase 1: Foundation Tests ═══"
# ══════════════════════════════════════════════════════════════════════════════

# T1.1 — Health Check
parse_response "$(curl_get "$BASE_URL/health")"
assert_status "T1.1 Health Check" 200 "$STATUS"
assert_json_field "T1.1 body" "$BODY" ".status" "ok"

# T1.2 — Unauthenticated Request Rejected
parse_response "$(curl_get "$BASE_URL/api/v1/auth/whoami")"
assert_status_oneof "T1.2 Unauth rejected" "$STATUS" 401 422

# T1.3 — Init (First Run) — idempotent: resets DB if already initialized
parse_response "$(curl_post "$BASE_URL/api/v1/auth/init" \
  '{"email":"testadmin@observal.dev","name":"Test Admin"}')"

if [ "$STATUS" -eq 200 ]; then
  API_KEY=$(echo "$BODY" | jq -r '.api_key')
  green "  ✓ T1.3 Init — got new API key"
  PASS=$((PASS + 1))
  assert_json_field "T1.3 role" "$BODY" ".user.role" "admin"
elif [ "$STATUS" -eq 400 ]; then
  yellow "  ↻ T1.3 Init — already initialized, resetting DB..."
  docker compose -f "$DOCKER_DIR/docker-compose.yml" down -v > /dev/null 2>&1
  docker compose -f "$DOCKER_DIR/docker-compose.yml" up -d > /dev/null 2>&1
  bold "  ⏳ Waiting for server after DB reset..."
  for i in $(seq 1 30); do
    if curl -sf "$BASE_URL/health" > /dev/null 2>&1; then break; fi
    if [ "$i" -eq 30 ]; then red "  Server not reachable after reset. Aborting."; exit 1; fi
    sleep 1
  done
  parse_response "$(curl_post "$BASE_URL/api/v1/auth/init" \
    '{"email":"testadmin@observal.dev","name":"Test Admin"}')"
  assert_status "T1.3 Init (after reset)" 200 "$STATUS"
  API_KEY=$(echo "$BODY" | jq -r '.api_key')
  assert_json_field "T1.3 role" "$BODY" ".user.role" "admin"
else
  assert_status "T1.3 Init" 200 "$STATUS"
fi

if [ -z "$API_KEY" ] || [ "$API_KEY" = "null" ]; then
  red "  ✗ T1.3 — API key is null/empty. Cannot continue."
  exit 1
fi

# T1.4 — Init (Already Initialized)
parse_response "$(curl_post "$BASE_URL/api/v1/auth/init" \
  '{"email":"admin2@test.com","name":"Admin2"}')"
assert_status "T1.4 Init duplicate" 400 "$STATUS"

# T1.5 — Whoami
parse_response "$(curl_get "$BASE_URL/api/v1/auth/whoami" -H "X-API-Key: $API_KEY")"
assert_status "T1.5 Whoami" 200 "$STATUS"
assert_json_field "T1.5 role" "$BODY" ".role" "admin"

# T1.6 — Login
parse_response "$(curl_post "$BASE_URL/api/v1/auth/login" \
  "{\"api_key\":\"$API_KEY\"}")"
assert_status "T1.6 Login" 200 "$STATUS"
assert_json_field "T1.6 role" "$BODY" ".role" "admin"

# T1.7 — Invalid API Key
parse_response "$(curl_get "$BASE_URL/api/v1/auth/whoami" -H "X-API-Key: invalid-key-here")"
assert_status "T1.7 Invalid key" 401 "$STATUS"

# ══════════════════════════════════════════════════════════════════════════════
bold ""
bold "═══ Phase 2: MCP Registry Tests ═══"
# ══════════════════════════════════════════════════════════════════════════════

AUTH=(-H "X-API-Key: $API_KEY")
LONG_DESC="This is a comprehensive test MCP server for integration testing purposes. It provides various utility tools and demonstrates the full lifecycle of MCP registration and validation."

# T2.4 — Submit MCP (Valid)
parse_response "$(curl_post "$BASE_URL/api/v1/mcps/submit" \
  "{
    \"git_url\": \"https://github.com/example/fastmcp-test.git\",
    \"name\": \"test-mcp-$(date +%s)\",
    \"version\": \"1.0.0\",
    \"description\": \"$LONG_DESC\",
    \"category\": \"utilities\",
    \"owner\": \"Platform Team\",
    \"supported_ides\": [\"cursor\", \"kiro\"],
    \"changelog\": \"Initial release\"
  }" "${AUTH[@]}")"
assert_status "T2.4 Submit valid" 200 "$STATUS"
assert_json_field "T2.4 status" "$BODY" ".status" "pending"
LISTING_ID=$(echo "$BODY" | jq -r '.id')
assert_json_nonempty "T2.4 id" "$BODY" ".id"

# T2.5 — Submit MCP (Description Too Short)
parse_response "$(curl_post "$BASE_URL/api/v1/mcps/submit" \
  '{
    "git_url": "https://github.com/example/fastmcp-test.git",
    "name": "bad-mcp",
    "version": "1.0.0",
    "description": "Too short",
    "category": "utilities",
    "owner": "Team",
    "supported_ides": []
  }' "${AUTH[@]}")"
assert_status "T2.5 Short desc" 422 "$STATUS"

# T2.6 — List MCPs (nothing approved yet for our new listing)
parse_response "$(curl_get "$BASE_URL/api/v1/mcps")"
assert_status "T2.6 List MCPs" 200 "$STATUS"

# T2.7 — Review List (Admin)
parse_response "$(curl_get "$BASE_URL/api/v1/review" "${AUTH[@]}")"
assert_status "T2.7 Review list" 200 "$STATUS"

# T2.8 — Review Show
parse_response "$(curl_get "$BASE_URL/api/v1/review/$LISTING_ID" "${AUTH[@]}")"
assert_status "T2.8 Review show" 200 "$STATUS"
assert_json_field "T2.8 id" "$BODY" ".id" "$LISTING_ID"

# T2.9 — Approve Listing
parse_response "$(curl_post "$BASE_URL/api/v1/review/$LISTING_ID/approve" '{}' "${AUTH[@]}")"
assert_status "T2.9 Approve" 200 "$STATUS"
assert_json_field "T2.9 status" "$BODY" ".status" "approved"

# T2.10 — List MCPs (After Approval)
parse_response "$(curl_get "$BASE_URL/api/v1/mcps")"
assert_status "T2.10 List after approve" 200 "$STATUS"

# T2.11 — List MCPs with Search
parse_response "$(curl_get "$BASE_URL/api/v1/mcps?search=test" )"
assert_status "T2.11 Search" 200 "$STATUS"

# T2.12 — List MCPs with Category Filter
parse_response "$(curl_get "$BASE_URL/api/v1/mcps?category=utilities")"
assert_status "T2.12 Category filter" 200 "$STATUS"

# T2.13 — Show MCP Detail
parse_response "$(curl_get "$BASE_URL/api/v1/mcps/$LISTING_ID")"
assert_status "T2.13 Show detail" 200 "$STATUS"
assert_json_field "T2.13 id" "$BODY" ".id" "$LISTING_ID"

# T2.14 — Install MCP (Cursor)
parse_response "$(curl_post "$BASE_URL/api/v1/mcps/$LISTING_ID/install" \
  '{"ide":"cursor"}' "${AUTH[@]}")"
assert_status "T2.14 Install cursor" 200 "$STATUS"
assert_json_nonempty "T2.14 snippet" "$BODY" ".config_snippet"

# T2.15 — Install MCP (Claude Code)
parse_response "$(curl_post "$BASE_URL/api/v1/mcps/$LISTING_ID/install" \
  '{"ide":"claude-code"}' "${AUTH[@]}")"
assert_status "T2.15 Install claude-code" 200 "$STATUS"

# T2.16 — Install MCP (Kiro)
parse_response "$(curl_post "$BASE_URL/api/v1/mcps/$LISTING_ID/install" \
  '{"ide":"kiro"}' "${AUTH[@]}")"
assert_status "T2.16 Install kiro" 200 "$STATUS"

# T2.17 — Install MCP (Gemini CLI)
parse_response "$(curl_post "$BASE_URL/api/v1/mcps/$LISTING_ID/install" \
  '{"ide":"gemini-cli"}' "${AUTH[@]}")"
assert_status "T2.17 Install gemini-cli" 200 "$STATUS"

# T2.18 — Reject Listing (submit a second one, then reject it)
parse_response "$(curl_post "$BASE_URL/api/v1/mcps/submit" \
  "{
    \"git_url\": \"https://github.com/example/reject-me.git\",
    \"name\": \"reject-mcp-$(date +%s)\",
    \"version\": \"1.0.0\",
    \"description\": \"$LONG_DESC\",
    \"category\": \"utilities\",
    \"owner\": \"Platform Team\",
    \"supported_ides\": [\"cursor\"]
  }" "${AUTH[@]}")"
REJECT_ID=$(echo "$BODY" | jq -r '.id')

parse_response "$(curl_post "$BASE_URL/api/v1/review/$REJECT_ID/reject" \
  '{"reason":"Description is misleading"}' "${AUTH[@]}")"
assert_status "T2.18 Reject" 200 "$STATUS"
assert_json_field "T2.18 status" "$BODY" ".status" "rejected"
assert_json_field "T2.18 reason" "$BODY" ".rejection_reason" "Description is misleading"

# T2.19 — Non-Admin Cannot Review (skip if no way to create non-admin user)
yellow "  ⊘ T2.19 Non-admin review — SKIPPED (requires non-admin user)"
SKIP=$((SKIP + 1))

# T2.20 — Install Unapproved Listing (use the rejected one)
parse_response "$(curl_post "$BASE_URL/api/v1/mcps/$REJECT_ID/install" \
  '{"ide":"cursor"}' "${AUTH[@]}")"
assert_status "T2.20 Install unapproved" 404 "$STATUS"

# ══════════════════════════════════════════════════════════════════════════════
# Cleanup: approve/reject are already idempotent. Submitted listings use
# unique timestamped names so re-runs don't collide.
# ══════════════════════════════════════════════════════════════════════════════

bold ""
bold "═══ Results ═══"
green "  Passed:  $PASS"
if [ "$FAIL" -gt 0 ]; then
  red "  Failed:  $FAIL"
  echo -e "  $FAILURES"
else
  green "  Failed:  0"
fi
if [ "$SKIP" -gt 0 ]; then
  yellow "  Skipped: $SKIP"
fi

bold ""
if [ "$FAIL" -gt 0 ]; then
  red "SOME TESTS FAILED"
  exit 1
else
  green "ALL TESTS PASSED ✓"
fi
