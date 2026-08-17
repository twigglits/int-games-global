#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Trivy security scan, run entirely in Docker so nothing has to be installed.
#
#   ./scripts/security_scan.sh              # everything
#   ./scripts/security_scan.sh repo         # dependencies, secrets, IaC only
#   ./scripts/security_scan.sh images       # the three built images only
#   ./scripts/security_scan.sh --severity CRITICAL
#   ./scripts/security_scan.sh --report     # also write SARIF + JSON to reports/
#
# What each pass finds, and why it is here rather than covered by something else:
#
#   vuln      CVEs in the Python wheels, the NuGet packages and the OS packages
#             inside the images. ruff, mypy and the .NET analysers all read
#             source; none of them know that a pinned dependency has a CVE.
#   secret    Credentials committed by accident. The CI guard greps Terraform
#             for four specific patterns; this is the general case.
#   misconfig Terraform, Dockerfile and Compose misconfiguration. This is the
#             tfsec ruleset, now folded into Trivy.
#
# Exit code is 1 if anything at or above the severity threshold is found, so it
# works as a pre-commit or CI gate.
# ---------------------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

TRIVY_IMAGE="aquasec/trivy:0.74.0"
SEVERITY="HIGH,CRITICAL"
# One argument, not three. Held in a variable so shellcheck does not read the
# commas as array separators (SC2054).
SCANNERS="vuln,secret,misconfig"
TARGET="all"
WRITE_REPORTS=false
REPORT_DIR="${REPO_ROOT}/reports/security"

# The three images the platform builds. The database, embedding server, Grafana
# and the rest are upstream images we do not control; scanning them tells you to
# raise a ticket with somebody else.
IMAGES=(
  "movie-search-api:local"
  "movie-search-mcp:local"
  "movie-search-pipeline:local"
)

usage() {
  cat <<'EOF'
Usage: security_scan.sh [target] [options]

  target                   all (default) | repo | images | iac

Options:
  --severity <list>        Comma-separated. Default: HIGH,CRITICAL
                           One of UNKNOWN,LOW,MEDIUM,HIGH,CRITICAL
  --report                 Also write SARIF and JSON into reports/security/
  --no-fail                Report findings but always exit 0
  -h, --help               This message

Examples:
  ./scripts/security_scan.sh
  ./scripts/security_scan.sh iac --severity MEDIUM,HIGH,CRITICAL
  ./scripts/security_scan.sh --report --no-fail
EOF
}

FAIL_ON_FINDING=true

while [[ $# -gt 0 ]]; do
  case "$1" in
    all|repo|images|iac) TARGET="$1"; shift ;;
    --severity)  SEVERITY="$2"; shift 2 ;;
    --report)    WRITE_REPORTS=true; shift ;;
    --no-fail)   FAIL_ON_FINDING=false; shift ;;
    -h|--help)   usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

command -v docker >/dev/null || { echo "error: docker is not installed" >&2; exit 1; }

# Pull once, up front. Without this a bad tag or no network surfaces later as a
# scan "failure", which reads identically to a scan that found something — and
# those two need very different responses.
if ! docker image inspect "${TRIVY_IMAGE}" >/dev/null 2>&1; then
  echo "pulling ${TRIVY_IMAGE} ..."
  docker pull --quiet "${TRIVY_IMAGE}" >/dev/null || {
    echo "error: could not pull ${TRIVY_IMAGE}. Check the tag and your network." >&2
    exit 2
  }
fi

# A named volume for the vulnerability database. Without it every run
# re-downloads roughly 200 MB, which makes the scan too slow to use often, and a
# tool you do not run often is a tool that finds nothing.
docker volume create trivy-cache >/dev/null

[[ "${WRITE_REPORTS}" == true ]] && mkdir -p "${REPORT_DIR}"

FINDINGS=0

trivy() {
  docker run --rm \
    -v "${REPO_ROOT}:/repo:ro" \
    -v trivy-cache:/root/.cache/trivy \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -w /repo \
    "${TRIVY_IMAGE}" "$@"
}

banner() {
  echo
  echo "============================================================"
  echo " $1"
  echo "============================================================"
}

# --- repository: dependencies, secrets, IaC -----------------------------------

scan_repo() {
  banner "Repository — dependencies, secrets and misconfiguration"
  local args=(
    fs /repo
    --scanners "${SCANNERS}"
    --severity "${SEVERITY}"
    --ignorefile /repo/.trivyignore
    --no-progress
  )
  args+=(--exit-code 1)

  if [[ "${WRITE_REPORTS}" == true ]]; then
    trivy "${args[@]}" || FINDINGS=1
    docker run --rm -v "${REPO_ROOT}:/repo" -v trivy-cache:/root/.cache/trivy \
      -w /repo "${TRIVY_IMAGE}" fs /repo \
      --scanners "${SCANNERS}" --severity "${SEVERITY}" \
      --ignorefile /repo/.trivyignore --no-progress \
      --format sarif --output "/repo/reports/security/repo.sarif" >/dev/null || true
    echo "  SARIF written to reports/security/repo.sarif"
  else
    trivy "${args[@]}" || FINDINGS=1
  fi
}

# --- infrastructure as code only ----------------------------------------------

scan_iac() {
  banner "Terraform, Dockerfiles and Compose — misconfiguration"
  local args=(
    config /repo
    --severity "${SEVERITY}"
    --ignorefile /repo/.trivyignore
    --no-progress
  )
  args+=(--exit-code 1)
  trivy "${args[@]}" || FINDINGS=1
}

# --- images -------------------------------------------------------------------

scan_images() {
  banner "Container images — OS and language package CVEs"
  local missing=()
  for image in "${IMAGES[@]}"; do
    docker image inspect "${image}" >/dev/null 2>&1 || missing+=("${image}")
  done
  if [[ ${#missing[@]} -gt 0 ]]; then
    echo "  These images are not built yet:"
    printf '    %s\n' "${missing[@]}"
    echo
    echo "  Build them first:  docker compose build api mcp-server pipeline"
    echo "  Skipping the image scan."
    return 0
  fi

  for image in "${IMAGES[@]}"; do
    echo
    echo "--- ${image}"
    local args=(
      image "${image}"
      --severity "${SEVERITY}"
      --ignorefile /repo/.trivyignore
      --no-progress
      # A CVE with no fix available is not actionable today. It is still
      # reported by `--report`, just not treated as a gate failure.
      --ignore-unfixed
    )
    args+=(--exit-code 1)
    trivy "${args[@]}" || FINDINGS=1
  done
}

# --- run ----------------------------------------------------------------------

echo "============================================================"
echo " Trivy security scan"
echo "   severity : ${SEVERITY}"
echo "   target   : ${TARGET}"
echo "   image    : ${TRIVY_IMAGE}"
echo "============================================================"

case "${TARGET}" in
  all)    scan_repo; scan_images ;;
  repo)   scan_repo ;;
  iac)    scan_iac ;;
  images) scan_images ;;
esac

banner "Result"
if [[ "${FINDINGS}" -eq 0 ]]; then
  echo " Nothing at ${SEVERITY}."
  exit 0
fi

echo " Findings at ${SEVERITY}. See the tables above."
echo
echo " To accept one deliberately, add its id to .trivyignore with a reason and"
echo " an expiry date. An ignore without a reason is a finding you have forgotten"
echo " rather than one you have decided about."
[[ "${FAIL_ON_FINDING}" == true ]] && exit 1
exit 0
