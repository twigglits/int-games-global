#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Run a SonarQube analysis locally. Starts the server if it is not up, produces
# coverage for both languages, runs the scanner, and prints the dashboard URL.
#
#   ./scripts/sonar_scan.sh                # everything
#   ./scripts/sonar_scan.sh --no-coverage  # skip the test runs, scan only
#   ./scripts/sonar_scan.sh --stop         # stop the server, keep its data
#   ./scripts/sonar_scan.sh --destroy      # stop and delete its data
#
# What this adds over what already runs in CI
# -------------------------------------------
# ruff, mypy --strict and the .NET analysers already gate the build, and they
# are better than Sonar at their own languages. Sonar earns its place on three
# things they cannot do:
#
#   * duplication across the whole repository, including across languages;
#   * cognitive complexity per function, with a threshold;
#   * one quality gate over three languages, instead of three separate verdicts.
#
# It is a local tool on purpose. Nothing in CI depends on it, so it can be down
# or absent without blocking anybody.
# ---------------------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

COMPOSE_FILE="docker-compose.sonar.yml"
SCANNER_IMAGE="sonarsource/sonar-scanner-cli:11"
SONAR_PORT="${SONAR_HOST_PORT:-9000}"
SONAR_URL="http://localhost:${SONAR_PORT}"
RUN_COVERAGE=true

usage() {
  cat <<'EOF'
Usage: sonar_scan.sh [options]

Options:
  --no-coverage    Skip running the test suites; scan without coverage data
  --stop           Stop the SonarQube container, keep its analysis history
  --destroy        Stop it and delete its volumes
  -h, --help       This message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-coverage) RUN_COVERAGE=false; shift ;;
    --stop)    docker compose -f "${COMPOSE_FILE}" down; exit 0 ;;
    --destroy) docker compose -f "${COMPOSE_FILE}" down -v; exit 0 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

command -v docker >/dev/null || { echo "error: docker is not installed" >&2; exit 1; }

# --- the mmap limit ------------------------------------------------------------
# SonarQube embeds Elasticsearch, which refuses to start under the default Linux
# mmap limit. Checked up front, because the failure mode otherwise is a container
# that exits during startup with the reason buried in its logs.
if [[ -r /proc/sys/vm/max_map_count ]]; then
  CURRENT="$(cat /proc/sys/vm/max_map_count)"
  if (( CURRENT < 262144 )); then
    echo "error: vm.max_map_count is ${CURRENT}; SonarQube's Elasticsearch needs 262144." >&2
    echo >&2
    echo "  Run this once, then try again:" >&2
    echo "    sudo sysctl -w vm.max_map_count=262144" >&2
    echo >&2
    echo "  To make it survive a reboot:" >&2
    echo "    echo 'vm.max_map_count=262144' | sudo tee /etc/sysctl.d/99-sonarqube.conf" >&2
    exit 1
  fi
fi

# --- start the server ----------------------------------------------------------

echo "============================================================"
echo " SonarQube analysis"
echo "   server : ${SONAR_URL}"
echo "============================================================"

if ! curl -fsS "${SONAR_URL}/api/system/status" 2>/dev/null | grep -q '"status":"UP"'; then
  echo "starting SonarQube (first run takes a couple of minutes) ..."
  docker compose -f "${COMPOSE_FILE}" up -d
  printf "waiting for it to come up "
  for _ in $(seq 1 80); do
    if curl -fsS "${SONAR_URL}/api/system/status" 2>/dev/null | grep -q '"status":"UP"'; then
      echo " up"
      break
    fi
    printf "."
    sleep 5
  done
  curl -fsS "${SONAR_URL}/api/system/status" 2>/dev/null | grep -q '"status":"UP"' || {
    echo
    echo "error: SonarQube did not come up. Its logs:" >&2
    docker compose -f "${COMPOSE_FILE}" logs --tail 40 sonarqube >&2
    exit 1
  }
else
  echo "SonarQube is already up."
fi

# --- credentials ---------------------------------------------------------------
# A first-run instance has admin/admin and demands a change before the API will
# do anything useful. Doing it here means the script works against a clean volume
# with no manual step in a browser.
#
# SonarQube 25 enforces a password policy — upper, lower, digit and symbol — and
# rejects anything weaker with a 400. The default below satisfies it. Override
# with SONAR_ADMIN_PASSWORD if you want your own, and make it comply.
ADMIN_PASSWORD="${SONAR_ADMIN_PASSWORD:-MovieSearch-Local-1}"

authenticates() {
  curl -fsS -u "admin:$1" "${SONAR_URL}/api/authentication/validate" 2>/dev/null \
    | grep -q '"valid":true'
}

if authenticates "${ADMIN_PASSWORD}"; then
  echo "admin password is already set."
elif authenticates "admin"; then
  echo "changing the default admin password ..."
  RESULT="$(curl -sS -u "admin:admin" -X POST "${SONAR_URL}/api/users/change_password" \
    -d "login=admin&previousPassword=admin&password=${ADMIN_PASSWORD}" 2>&1 || true)"
  if ! authenticates "${ADMIN_PASSWORD}"; then
    echo "error: could not change the admin password." >&2
    echo "  SonarQube said: ${RESULT}" >&2
    echo "  Set SONAR_ADMIN_PASSWORD to something that meets its policy and retry." >&2
    exit 1
  fi
else
  echo "error: cannot authenticate as admin with either the default or ${ADMIN_PASSWORD}." >&2
  echo "  If you changed it by hand, export SONAR_ADMIN_PASSWORD and retry." >&2
  echo "  To start over:  ./scripts/sonar_scan.sh --destroy" >&2
  exit 1
fi

# A fresh token per run. Revoking first makes the script re-runnable; without it
# the second run fails because the name is taken.
TOKEN_NAME="local-scan"
curl -fsS -u "admin:${ADMIN_PASSWORD}" -X POST "${SONAR_URL}/api/user_tokens/revoke" \
  -d "name=${TOKEN_NAME}" >/dev/null 2>&1 || true

SONAR_TOKEN="$(curl -fsS -u "admin:${ADMIN_PASSWORD}" -X POST \
  "${SONAR_URL}/api/user_tokens/generate" -d "name=${TOKEN_NAME}" 2>/dev/null \
  | python3 -c 'import json,sys; print(json.load(sys.stdin).get("token",""))' 2>/dev/null || true)"

[[ -n "${SONAR_TOKEN}" ]] || { echo "error: could not generate a scanner token" >&2; exit 1; }

# --- coverage ------------------------------------------------------------------

if [[ "${RUN_COVERAGE}" == true ]]; then
  echo
  echo "--- coverage: Python"
  for service in pipeline mcp-server; do
    if [[ -x "${service}/.venv/bin/python" ]]; then
      ( cd "${service}" && .venv/bin/python -m pytest -q \
          --cov=src --cov-report=xml >/dev/null 2>&1 ) \
        && echo "  ${service}: coverage.xml written" \
        || echo "  ${service}: tests failed; coverage not written"
    else
      echo "  ${service}: no .venv, skipped. Create one with: cd ${service} && python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'"
    fi
  done

  echo "--- coverage: .NET"
  if command -v dotnet >/dev/null || [[ -x "${HOME}/.dotnet/dotnet" ]]; then
    export PATH="${HOME}/.dotnet:${PATH}"
    ( cd api && dotnet test tests/MovieSearch.Tests/MovieSearch.Tests.csproj \
        --collect:"XPlat Code Coverage;Format=opencover" \
        --results-directory ./coverage >/dev/null 2>&1 ) \
      && echo "  api: opencover written to api/coverage/" \
      || echo "  api: coverage run failed. The .NET 10 test host is Microsoft.Testing.Platform; see README section 15."
  else
    echo "  api: no dotnet SDK on PATH, skipped"
  fi
fi

# --- scan ----------------------------------------------------------------------

echo
echo "--- running the scanner"
docker run --rm \
  --network host \
  -v "${REPO_ROOT}:/usr/src" \
  -e SONAR_HOST_URL="${SONAR_URL}" \
  -e SONAR_TOKEN="${SONAR_TOKEN}" \
  "${SCANNER_IMAGE}"

cat <<EOF

============================================================
 Done.

   Dashboard : ${SONAR_URL}/dashboard?id=movie-search-platform
   Login     : admin / ${ADMIN_PASSWORD}

 Stop it when you are finished; it holds 2 GB of memory:
   ./scripts/sonar_scan.sh --stop
============================================================
EOF
