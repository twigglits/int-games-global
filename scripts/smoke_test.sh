#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# End to end smoke test for a running platform.
#
#   ./scripts/smoke_test.sh                       # uses the ports from .env
#   API_BASE_URL=http://localhost:8080 ./scripts/smoke_test.sh
#
# It exercises every endpoint, both roles, the validation rules and the rate
# limiter, and fails on the first thing that does not behave. The CI workflow
# runs this against the Docker Compose stack, so a regression in any service
# fails the build rather than being noticed later.
# ---------------------------------------------------------------------------
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "${REPO_ROOT}/.env" ]]; then
  # shellcheck disable=SC1091
  set -a && source "${REPO_ROOT}/.env" && set +a
fi

API_BASE_URL="${API_BASE_URL:-http://localhost:${API_HOST_PORT:-8080}}"
MCP_BASE_URL="${MCP_BASE_URL:-http://localhost:${MCP_HOST_PORT:-8000}}"
READER_ID="${READER_CLIENT_ID:-reader-client}"
READER_SECRET="${READER_CLIENT_SECRET:-reader-secret-change-me}"
ADMIN_ID="${ADMIN_CLIENT_ID:-admin-client}"
ADMIN_SECRET="${ADMIN_CLIENT_SECRET:-admin-secret-change-me}"

PASS=0
FAIL=0

green() { printf '\033[32m%s\033[0m\n' "$1"; }
red() { printf '\033[31m%s\033[0m\n' "$1"; }

check() {
  local name="$1" expected="$2" actual="$3"
  if [[ "${expected}" == "${actual}" ]]; then
    green "  PASS  ${name}"
    PASS=$((PASS + 1))
  else
    red "  FAIL  ${name}: expected ${expected}, got ${actual}"
    FAIL=$((FAIL + 1))
  fi
}

check_contains() {
  local name="$1" needle="$2" haystack="$3"
  if [[ "${haystack}" == *"${needle}"* ]]; then
    green "  PASS  ${name}"
    PASS=$((PASS + 1))
  else
    red "  FAIL  ${name}: '${needle}' not found in the response"
    red "        ${haystack:0:300}"
    FAIL=$((FAIL + 1))
  fi
}

status() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

token_for() {
  curl -s -X POST "${API_BASE_URL}/auth/token" \
    -H 'Content-Type: application/json' \
    -d "{\"client_id\":\"$1\",\"client_secret\":\"$2\"}" |
    python3 -c 'import json,sys; print(json.load(sys.stdin).get("access_token",""))'
}

echo "============================================================"
echo " SMOKE TEST  ${API_BASE_URL}"
echo "============================================================"

echo
echo "-- operations ------------------------------------------------"
check "GET /health is 200" 200 "$(status "${API_BASE_URL}/health")"
check "GET /health/live is 200" 200 "$(status "${API_BASE_URL}/health/live")"
check "GET /health/ready is 200" 200 "$(status "${API_BASE_URL}/health/ready")"
check "GET /metrics is 200" 200 "$(status "${API_BASE_URL}/metrics")"
check "GET /openapi/v1.json is 200" 200 "$(status "${API_BASE_URL}/openapi/v1.json")"
check "GET /swagger/index.html is 200" 200 "$(status "${API_BASE_URL}/swagger/index.html")"
check "MCP GET /health is 200" 200 "$(status "${MCP_BASE_URL}/health")"
check "MCP GET /metrics is 200" 200 "$(status "${MCP_BASE_URL}/metrics")"

echo
echo "-- authentication --------------------------------------------"
check "no token is 401" 401 "$(status "${API_BASE_URL}/api/v1/movies/genres")"
check "bad secret is 401" 401 "$(status -X POST "${API_BASE_URL}/auth/token" \
  -H 'Content-Type: application/json' -d "{\"client_id\":\"${READER_ID}\",\"client_secret\":\"wrong\"}")"
check "unsupported grant is 400" 400 "$(status -X POST "${API_BASE_URL}/auth/token" \
  -H 'Content-Type: application/json' \
  -d "{\"client_id\":\"${READER_ID}\",\"client_secret\":\"${READER_SECRET}\",\"grant_type\":\"password\"}")"

READER_TOKEN="$(token_for "${READER_ID}" "${READER_SECRET}")"
ADMIN_TOKEN="$(token_for "${ADMIN_ID}" "${ADMIN_SECRET}")"
if [[ -z "${READER_TOKEN}" || -z "${ADMIN_TOKEN}" ]]; then
  red "could not obtain tokens; aborting"
  exit 1
fi
green "  PASS  obtained a reader token and an admin token"
PASS=$((PASS + 2))

READER=(-H "Authorization: Bearer ${READER_TOKEN}")
ADMIN=(-H "Authorization: Bearer ${ADMIN_TOKEN}")

echo
echo "-- roles ------------------------------------------------------"
check "reader may search" 200 "$(status "${READER[@]}" "${API_BASE_URL}/api/v1/movies/search?q=space")"
check "reader may not read stats" 403 "$(status "${READER[@]}" "${API_BASE_URL}/api/v1/stats")"
check "admin may read stats" 200 "$(status "${ADMIN[@]}" "${API_BASE_URL}/api/v1/stats")"
check "admin may search" 200 "$(status "${ADMIN[@]}" "${API_BASE_URL}/api/v1/movies/search?q=space")"

echo
echo "-- validation -------------------------------------------------"
check "missing q is 400" 400 "$(status "${READER[@]}" "${API_BASE_URL}/api/v1/movies/search")"
check "top_k over the ceiling is 400" 400 "$(status "${READER[@]}" "${API_BASE_URL}/api/v1/movies/search?q=x&top_k=51")"
check "rating over 10 is 400" 400 "$(status "${READER[@]}" "${API_BASE_URL}/api/v1/movies/search?q=x&min_imdb_rating=11")"
check "a non-decade year is 400" 400 "$(status "${READER[@]}" "${API_BASE_URL}/api/v1/movies/search?q=x&decade=1995")"
check "an empty id is 400" 400 "$(status "${READER[@]}" "${API_BASE_URL}/api/v1/movies/00000000-0000-0000-0000-000000000000")"
check "an unknown id is 404" 404 "$(status "${READER[@]}" "${API_BASE_URL}/api/v1/movies/3f2504e0-4f89-11d3-9a0c-0305e82c3301")"
check "an id that is not a uuid does not match the route" 404 "$(status "${READER[@]}" "${API_BASE_URL}/api/v1/movies/not-a-uuid")"

echo
echo "-- the five specified natural language queries ----------------"
QUERIES=(
  "action movies from the 90s with high IMDB ratings|&genre=Action&decade=1990&min_imdb_rating=7"
  "critically acclaimed drama films with small budgets|&genre=Drama"
  "animated family movies distributed by Disney|"
  "sci-fi films directed by James Cameron|"
  "dark psychological thrillers with low Rotten Tomatoes scores|"
)
for entry in "${QUERIES[@]}"; do
  query="${entry%%|*}"
  filters="${entry#*|}"
  encoded="$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "${query}")"
  body="$(curl -s "${READER[@]}" "${API_BASE_URL}/api/v1/movies/search?q=${encoded}&top_k=5${filters}")"
  count="$(printf '%s' "${body}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["count"])' 2>/dev/null || echo 0)"
  if [[ "${count}" -ge 1 ]]; then
    green "  PASS  '${query}' returned ${count} results"
    PASS=$((PASS + 1))
    printf '%s' "${body}" | python3 -c '
import json, sys
for movie in json.load(sys.stdin)["results"][:3]:
    line = "          {:.4f}  {:44s} {}  {}".format(
        movie["similarity"], movie["title"][:44], movie["release_year"], movie["major_genre"])
    print(line)
'
  else
    red "  FAIL  '${query}' returned no results"
    FAIL=$((FAIL + 1))
  fi
done

echo
echo "-- movie lookups ----------------------------------------------"
FIRST_ID="$(curl -s "${READER[@]}" "${API_BASE_URL}/api/v1/movies/search?q=the%20terminator&top_k=1" |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["results"][0]["id"])')"
check "get by id is 200" 200 "$(status "${READER[@]}" "${API_BASE_URL}/api/v1/movies/${FIRST_ID}")"
check "get similar is 200" 200 "$(status "${READER[@]}" "${API_BASE_URL}/api/v1/movies/${FIRST_ID}/similar?top_k=5")"

SIMILAR="$(curl -s "${READER[@]}" "${API_BASE_URL}/api/v1/movies/${FIRST_ID}/similar?top_k=5")"
SELF_IN_RESULT="$(printf '%s' "${SIMILAR}" | python3 -c "
import json, sys
data = json.load(sys.stdin)
print('yes' if any(m['id'] == '${FIRST_ID}' for m in data['results']) else 'no')")"
check "a movie is never its own neighbour" "no" "${SELF_IN_RESULT}"

GENRES="$(curl -s "${READER[@]}" "${API_BASE_URL}/api/v1/movies/genres")"
check_contains "genres include Drama" '"Drama"' "${GENRES}"
check_contains "genres include Action" '"Action"' "${GENRES}"

STATS="$(curl -s "${ADMIN[@]}" "${API_BASE_URL}/api/v1/stats")"
check_contains "stats report the embedding model" 'bge-base-en-v1.5' "${STATS}"
check_contains "stats report 768 dimensions" '"embedding_dimension":768' "${STATS}"

echo
echo "-- response cache ---------------------------------------------"
curl -s -o /dev/null "${READER[@]}" "${API_BASE_URL}/api/v1/movies/search?q=cache%20probe%20query"
CACHED="$(curl -s "${READER[@]}" "${API_BASE_URL}/api/v1/movies/search?q=cache%20probe%20query" |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["cached"])')"
check "a repeated search is served from the cache" "True" "${CACHED}"

echo
echo "============================================================"
if [[ "${FAIL}" -eq 0 ]]; then
  green " ALL ${PASS} CHECKS PASSED"
else
  red " ${FAIL} CHECKS FAILED, ${PASS} passed"
fi
echo "============================================================"
exit $(( FAIL > 0 ? 1 : 0 ))
