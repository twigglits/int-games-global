#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Write one environment's configuration and secrets into AWS, so that
# `terraform apply` needs no -var flags and no secret value ever reaches the
# Terraform state file.
#
# Two stores, split by what the value is:
#
#   Parameter Store   /<project>/<env>/config/...    the configuration. Not
#                     secret, no rotation, free at the standard tier.
#   Secrets Manager   <project>/<env>/...            the four secrets. Rotation,
#                     a resource policy per secret, staged version labels.
#                     $0.40 per secret per month.
#
#   ./scripts/bootstrap_parameters.sh dev
#   ./scripts/bootstrap_parameters.sh prod --region eu-west-1
#
# Run it once per environment, before the first `terraform apply`. It is safe to
# re-run: an existing value is left alone unless you name it explicitly.
#
# The secrets are generated here, on your machine, and are written straight to
# Secrets Manager. They are never printed, never written to a file, and never
# passed to Terraform.
# ---------------------------------------------------------------------------
set -euo pipefail

PROJECT="${PROJECT:-movie-search}"
REGION="${AWS_REGION:-eu-west-1}"
ENVIRONMENT=""
FORCE_KEYS=()
ROTATE=""

usage() {
  cat <<'EOF'
Usage: bootstrap_parameters.sh <environment> [options]

  <environment>            dev, staging or prod

Options:
  --region <region>        AWS region. Default: $AWS_REGION, or eu-west-1
  --project <name>         Project name, the first path segment. Default: movie-search
  --kms-key-id <id>        Customer managed KMS key for the secrets.
                           Default: the AWS managed alias/aws/secretsmanager key
  --overwrite <key>        Rewrite one value that already exists. Repeatable.
                           Example: --overwrite config/domain-name
  --rotate <name>          Generate and write a new value for one secret, then
                           print what to do next. One of:
                             database-password | jwt-signing-key | client:<id>
  --dry-run                Print what would be written; change nothing
  -h, --help               This message

Examples:
  ./scripts/bootstrap_parameters.sh dev
  ./scripts/bootstrap_parameters.sh dev --overwrite config/domain-name
  ./scripts/bootstrap_parameters.sh prod --rotate jwt-signing-key
EOF
}

KMS_KEY_ID=""
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    dev|staging|prod) ENVIRONMENT="$1"; shift ;;
    --region)     REGION="$2"; shift 2 ;;
    --project)    PROJECT="$2"; shift 2 ;;
    --kms-key-id) KMS_KEY_ID="$2"; shift 2 ;;
    --overwrite)  FORCE_KEYS+=("$2"); shift 2 ;;
    --rotate)     ROTATE="$2"; shift 2 ;;
    --dry-run)    DRY_RUN=true; shift ;;
    -h|--help)    usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ -z "${ENVIRONMENT}" ]]; then
  echo "error: an environment is required" >&2
  usage
  exit 2
fi

ROOT="/${PROJECT}/${ENVIRONMENT}"
# Secrets Manager names carry no leading slash. The slashes that remain are what
# make the console render the secrets as a tree.
SECRET_PREFIX="${PROJECT}/${ENVIRONMENT}"

command -v aws >/dev/null || { echo "error: the AWS CLI is not installed" >&2; exit 1; }
command -v openssl >/dev/null || { echo "error: openssl is not installed" >&2; exit 1; }

ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
echo "============================================================"
echo " Configuration and secret bootstrap"
echo "   account     : ${ACCOUNT}"
echo "   region      : ${REGION}"
echo "   parameters  : ${ROOT}/config/...      (Parameter Store)"
echo "   secrets     : ${SECRET_PREFIX}/...    (Secrets Manager)"
echo "============================================================"
echo

# --- helpers ----------------------------------------------------------------

exists() {
  aws ssm get-parameter --name "$1" --region "${REGION}" >/dev/null 2>&1
}

# A secret scheduled for deletion still occupies its name, and create-secret
# fails on it. describe-secret succeeds either way, so the recovery window is
# reported rather than hit as an opaque error later.
secret_exists() {
  aws secretsmanager describe-secret --secret-id "$1" --region "${REGION}" >/dev/null 2>&1
}

secret_pending_deletion() {
  local deleted
  deleted="$(aws secretsmanager describe-secret --secret-id "$1" --region "${REGION}" \
    --query 'DeletedDate' --output text 2>/dev/null || echo "None")"
  [[ "${deleted}" != "None" && -n "${deleted}" ]]
}

forced() {
  local key="$1"
  for candidate in ${FORCE_KEYS[@]+"${FORCE_KEYS[@]}"}; do
    [[ "${candidate}" == "${key}" ]] && return 0
  done
  return 1
}

# put <relative-key> <value> <description>
# Configuration only. Nothing secret goes through this path.
put() {
  local key="$1" value="$2" description="$3"
  local name="${ROOT}/${key}"

  if exists "${name}" && ! forced "${key}"; then
    printf '  skip     %-42s (already set)\n' "${key}"
    return 0
  fi

  local action="write"
  exists "${name}" && action="OVERWRITE"

  if [[ "${DRY_RUN}" == true ]]; then
    printf '  %-8s %-42s %s\n' "${action}" "${key}" "${value}"
    return 0
  fi

  aws ssm put-parameter \
    --name "${name}" --type String --value "${value}" \
    --description "${description}" --region "${REGION}" \
    --overwrite --tier Standard >/dev/null
  aws ssm add-tags-to-resource \
    --resource-type Parameter --resource-id "${name}" --region "${REGION}" \
    --tags "Key=Project,Value=${PROJECT}" "Key=Environment,Value=${ENVIRONMENT}" \
           "Key=ManagedBy,Value=bootstrap-script" >/dev/null 2>&1 || true

  printf '  %-8s %-42s %s\n' "${action}" "${key}" "${value}"
}

# put_secret <relative-key> <value> <description>
# The value is passed on the command line, so it is visible in this process's
# argv for the length of the call. That is the same exposure the AWS CLI has for
# any --secret-string, and it never leaves the machine except over TLS.
put_secret() {
  local key="$1" value="$2" description="$3"
  local name="${SECRET_PREFIX}/${key}"

  if secret_pending_deletion "${name}"; then
    printf '  BLOCKED  %-42s scheduled for deletion\n' "${key}"
    echo "           Restore it, or purge the name:" >&2
    echo "             aws secretsmanager restore-secret --secret-id ${name} --region ${REGION}" >&2
    echo "             aws secretsmanager delete-secret --secret-id ${name} --region ${REGION} \\" >&2
    echo "               --force-delete-without-recovery" >&2
    return 1
  fi

  if secret_exists "${name}" && ! forced "${key}"; then
    printf '  skip     %-42s (already set)\n' "${key}"
    return 0
  fi

  local action="write"
  secret_exists "${name}" && action="ROTATE"

  if [[ "${DRY_RUN}" == true ]]; then
    printf '  %-8s %-42s <generated secret>\n' "${action}" "${key}"
    return 0
  fi

  if secret_exists "${name}"; then
    # A new version, labelled AWSCURRENT. The previous one becomes AWSPREVIOUS,
    # which is what makes a rollback possible without regenerating anything.
    aws secretsmanager put-secret-value \
      --secret-id "${name}" --secret-string "${value}" --region "${REGION}" >/dev/null
  else
    local -a args=(
      --name "${name}"
      --secret-string "${value}"
      --description "${description}"
      --region "${REGION}"
      --tags "Key=Project,Value=${PROJECT}" "Key=Environment,Value=${ENVIRONMENT}"
             "Key=ManagedBy,Value=bootstrap-script"
    )
    [[ -n "${KMS_KEY_ID}" ]] && args+=(--kms-key-id "${KMS_KEY_ID}")
    aws secretsmanager create-secret "${args[@]}" >/dev/null
  fi

  printf '  %-8s %-42s <generated, not shown>\n' "${action}" "${key}"
}

# Ask for a value, offering a default. Reads from the terminal, so it still
# works when the script's stdout is piped somewhere.
ask() {
  local prompt="$1" default="${2:-}" answer=""
  # Not a terminal (CI, or a piped run): take the default. "-" is the sentinel
  # the Terraform side reads as null, and Parameter Store rejects an empty value.
  if [[ ! -t 0 ]]; then
    echo "${default:--}"
    return
  fi
  if [[ -n "${default}" ]]; then
    read -r -p "  ${prompt} [${default}]: " answer </dev/tty
    echo "${answer:-${default}}"
  else
    read -r -p "  ${prompt} (blank to leave unset): " answer </dev/tty
    echo "${answer:--}"
  fi
}

# 48 alphanumeric characters, about 285 bits. Alphanumeric on purpose: RDS
# rejects '/', '@', '"' and space in a master password, and base64 produces '/'.
# The same alphabet is used for every secret so that one generator serves all.
secret() {
  local raw
  raw="$(openssl rand -base64 96)"
  raw="${raw//[^A-Za-z0-9]/}"
  printf '%s' "${raw:0:48}"
}

# --- rotation ----------------------------------------------------------------

if [[ -n "${ROTATE}" ]]; then
  case "${ROTATE}" in
    database-password) KEY="database-password" ;;
    jwt-signing-key)   KEY="jwt-signing-key" ;;
    client:*)          KEY="clients/${ROTATE#client:}" ;;
    *) echo "error: unknown secret '${ROTATE}'" >&2; exit 2 ;;
  esac

  echo "Rotating ${SECRET_PREFIX}/${KEY}"
  FORCE_KEYS=("${KEY}")
  put_secret "${KEY}" "$(secret)" "Rotated by bootstrap_parameters.sh"
  echo
  echo "Next steps:"
  if [[ "${ROTATE}" == "database-password" ]]; then
    cat <<EOF
  1. Increment database_password_version in terraform/environments/${ENVIRONMENT}/main.tf
     (Terraform cannot see a write-only value, so the counter is what tells it
      the password changed.)
  2. terraform apply     # RDS takes the new password
  3. Force a new deployment so the running tasks pick it up:
       for s in api mcp-server; do
         aws ecs update-service --cluster ${PROJECT}-${ENVIRONMENT}-cluster \\
           --service "\$s" --force-new-deployment --region ${REGION}
       done
EOF
  else
    cat <<EOF
  A running task holds the old value until it is replaced. Force a new
  deployment so the change takes effect:
    aws ecs update-service --cluster ${PROJECT}-${ENVIRONMENT}-cluster \\
      --service api --force-new-deployment --region ${REGION}
EOF
  fi
  exit 0
fi

# --- configuration ------------------------------------------------------------

echo "Configuration  (${ROOT}/config)"
echo "  These are not secrets. Terraform reads them at plan time."
echo

DOMAIN_DEFAULT="api-${ENVIRONMENT}.example.com"
[[ "${ENVIRONMENT}" == "prod" ]] && DOMAIN_DEFAULT="api.example.com"

DOMAIN="$(ask 'Public host name of the API' "${DOMAIN_DEFAULT}")"
ZONE_ID="$(ask 'Route 53 hosted zone id that owns it')"
CERT_ARN="$(ask 'Existing ACM certificate ARN, if you already have one')"
OIDC_ARN="$(ask 'GitHub Actions OIDC provider ARN, for CI deployment')"
ALARM_TOPIC="$(ask 'Existing SNS topic ARN for alarms')"
LOGS_BUCKET="$(ask 'S3 bucket for load balancer access logs')"
echo

put "config/domain-name"              "${DOMAIN}"      "Public host name of the API"
put "config/route53-zone-id"          "${ZONE_ID}"     "Hosted zone that owns the domain"
put "config/certificate-arn"          "${CERT_ARN}"    "Existing ACM certificate, or - to have Terraform request one"
put "config/github-oidc-provider-arn" "${OIDC_ARN}"    "GitHub Actions OIDC provider, or - to skip the deploy role"
put "config/alarm-topic-arn"          "${ALARM_TOPIC}" "SNS topic for alarms, or - to have Terraform create one"
put "config/alb-access-logs-bucket"   "${LOGS_BUCKET}" "S3 bucket for ALB access logs, or - for none"

# --- secrets --------------------------------------------------------------------

echo
echo "Secrets  (${SECRET_PREFIX})"
echo "  Generated here, written straight to Secrets Manager."
echo "  They are never printed and never reach the Terraform state file."
echo

put_secret "database-password"     "$(secret)" "RDS master password"
put_secret "jwt-signing-key"       "$(secret)" "API access token signing key"
put_secret "clients/reader-client" "$(secret)" "Client secret for the reader client"
put_secret "clients/admin-client"  "$(secret)" "Client secret for the admin client"

# --- summary ---------------------------------------------------------------------

echo
echo "============================================================"
if [[ "${DRY_RUN}" == true ]]; then
  echo " DRY RUN. Nothing was written."
else
  echo " Done."
  echo
  echo " Parameter Store (${ROOT}/config):"
  aws ssm get-parameters-by-path --path "${ROOT}/config" --recursive --region "${REGION}" \
    --query 'Parameters[].Name' --output text | tr '\t' '\n' | sed 's/^/   /' || true
  echo
  echo " Secrets Manager (${SECRET_PREFIX}):"
  aws secretsmanager list-secrets --region "${REGION}" \
    --filters "Key=name,Values=${SECRET_PREFIX}/" \
    --query 'SecretList[].Name' --output text | tr '\t' '\n' | sed 's/^/   /' || true
  cat <<EOF

 Next:
   cd terraform/environments/${ENVIRONMENT}
   terraform init
   terraform plan -out=${ENVIRONMENT}.tfplan     # no -var flags needed

 To read a secret back:
   aws secretsmanager get-secret-value --region ${REGION} \\
     --secret-id ${SECRET_PREFIX}/clients/reader-client \\
     --query SecretString --output text
EOF
fi
echo "============================================================"
