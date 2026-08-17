# Terraform — AWS deployment

This directory deploys the whole platform to AWS: a VPC, an ECS Fargate cluster
running the three services, an RDS PostgreSQL instance with pgvector, an
Application Load Balancer with HTTPS, every credential in AWS Secrets Manager and
every configuration value in Parameter Store, and CloudWatch and X-Ray for
observability.

**No secret value is ever written to the Terraform state file.** How that is
achieved is described in [Secrets and configuration](#secrets-and-configuration)
below, and enforced by a check in CI.

The orchestrator choice is argued in [`ECS_EKS_CHOICE.md`](../ECS_EKS_CHOICE.md)
at the repository root.

> **Deploying for the first time?** Read in this order:
> [Prerequisites](#prerequisites) for the state backend,
> [Secrets and configuration](#secrets-and-configuration) for the one bootstrap
> step, then [Deploying, step by step](#deploying-step-by-step). [Cost](#cost)
> and [Destroying an environment](#destroying-an-environment) are worth reading
> before you apply, not after.

---

## Layout

```
terraform/
├── main.tf            # composes the modules; declares no provider and no backend
├── variables.tf       # every input, with a description and a default
├── outputs.tf         # URLs, ARNs and ready-made commands
├── versions.tf        # Terraform and provider version constraints
├── modules/
│   ├── networking/    # VPC, three subnet tiers, NAT, endpoints, flow logs, security groups
│   ├── ecr/           # one repository per image, immutable tags, lifecycle policy
│   ├── secrets/       # reads both stores: config values and secret ARNs. Creates nothing
│   ├── iam/           # task execution role, task role, GitHub OIDC deployment role
│   ├── rds/           # PostgreSQL 16, private subnets, encrypted, Multi-AZ in prod
│   ├── alb/           # load balancer, ACM certificate, HTTPS listener, HTTP redirect
│   ├── compute/       # ECS cluster, three services, the pipeline task, autoscaling
│   └── monitoring/    # X-Ray sampling, CloudWatch alarms, dashboard
└── environments/
    ├── dev/           # backend, provider and the development settings
    └── prod/          # backend, provider and the production settings
```

The root is a **child module**. It declares no `provider` and no `backend`, so
each environment supplies its own and keeps its own state. Run Terraform from an
environment directory, never from the root.

---

## What the two environments differ in

| Setting | `dev` | `prod` | Why |
| --- | --- | --- | --- |
| Availability zones | 2 | 3 | Production survives losing a zone with capacity to spare. |
| NAT gateways | 1 shared | 1 per zone | A shared gateway is a single point of failure and a cross-zone data charge. |
| Interface VPC endpoints | off | on | They cost an hourly rate per zone and save NAT data charges at production volume. |
| RDS | single AZ, `db.t4g.medium` | Multi-AZ, `db.r7g.large` | Vector search is memory bound; the standby removes a single point of failure. |
| Backup retention | 1 day | 30 days | |
| Deletion protection | off | on | `dev` must be destroyable. |
| Image tags | mutable, `latest` allowed | immutable, `latest` refused | In production nobody should have to ask which code is running. |
| Fargate Spot | allowed | never | An interruption in `dev` costs a restart. |
| `ecs execute-command` | allowed | refused | It is a shell into a running container. |
| X-Ray sampling | 100% | 10% plus a reservoir | `dev` traffic is small enough to trace whole. |
| Log retention | 7 days | 90 days | |

Everything above is a variable. There is one copy of the infrastructure code.

---

## Prerequisites

| Tool | Version |
| --- | --- |
| Terraform | **1.11 or later** — write-only arguments |
| AWS CLI | 2.x, with credentials that can create the resources |
| A Route 53 hosted zone | For the API domain and the ACM validation records |

You also need the state backend, which is created once per account and is
deliberately **not** managed by this configuration: a configuration cannot
create the bucket that holds its own state.

```bash
REGION=eu-west-1
BUCKET=movie-search-terraform-state
TABLE=movie-search-terraform-locks

# Versioned and encrypted. The state holds no secret, but it does hold every
# endpoint, ARN and security group rule in the account.
aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
  --create-bucket-configuration LocationConstraint="$REGION"
aws s3api put-bucket-versioning --bucket "$BUCKET" \
  --versioning-configuration Status=Enabled
aws s3api put-bucket-encryption --bucket "$BUCKET" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws s3api put-public-access-block --bucket "$BUCKET" \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

# The lock table stops two applies from running at once.
aws dynamodb create-table --table-name "$TABLE" --region "$REGION" \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST
```

> The state file holds no secret. It still holds infrastructure detail worth
> protecting — endpoints, ARNs, security group rules — so the bucket above is
> private, encrypted and versioned. But losing it no longer means losing the
> database password.
>
> The bucket lives in the **same account** as the infrastructure it describes,
> which is a considered trade for a demonstration and not the pattern to keep.
> The risk, the target architecture and the migration steps are written up in the
> main [README, "Hardening the Terraform state"](../README.md#hardening-the-terraform-state).

---

## Secrets and configuration

Every environment reads its configuration and its secrets from AWS, never from a
`-var` flag. Terraform creates neither; `scripts/bootstrap_parameters.sh` writes
both once, before the first apply.

Two stores, split by what the value is. A hostname and a password want different
things from a store, so they get different stores.

| | Holds | Why |
| --- | --- | --- |
| **Parameter Store** | The six configuration values | Not secret, no rotation, and the standard tier is free |
| **Secrets Manager** | The four secrets | Rotation with a Lambda, a resource policy per secret, cross-account sharing, and `AWSCURRENT`/`AWSPREVIOUS` version labels so a rotation does not break running tasks. $0.40 per secret per month |

```
Parameter Store (String)
  /movie-search/dev/config/domain-name                required
  /movie-search/dev/config/route53-zone-id            optional
  /movie-search/dev/config/certificate-arn            optional
  /movie-search/dev/config/github-oidc-provider-arn   optional
  /movie-search/dev/config/alarm-topic-arn            optional
  /movie-search/dev/config/alb-access-logs-bucket     optional

Secrets Manager                                       (no leading slash)
  movie-search/dev/database-password
  movie-search/dev/jwt-signing-key
  movie-search/dev/clients/reader-client
  movie-search/dev/clients/admin-client
```

An optional configuration value that is not set holds `-`, which the Terraform
side reads as null. The tree is therefore a complete contract rather than a set
of holes.

### Why no secret reaches the state file

Choosing Secrets Manager does not achieve this on its own. A plain
`data "aws_secretsmanager_secret_version"` **fetches the value and stores it in
state**, exactly as `random_password` did — and it differs from the ephemeral
resource this repository does use by a single keyword. Different mechanisms are
used instead, one per kind of consumer:

| Value | Who needs it | Mechanism | In state |
| --- | --- | --- | --- |
| All four secrets | Nobody, at plan time | `data "aws_secretsmanager_secret"` — singular, no `_version`. Returns the ARN, the KMS key and the tags. It does not return the value | The ARN only, which is not a secret |
| Signing key, client secrets | The ECS agent only | The ARN goes into the task definition's `secrets` block. The agent reads the value itself at task start | No |
| Database password | RDS, at create time | `ephemeral "aws_secretsmanager_secret_version"` feeds the write-only `password_wo` argument. Neither is persisted | No |
| Config values | Terraform, at plan time | `data "aws_ssm_parameters_by_path"`, one call for the subtree | Yes, and correctly so: a domain name is not a secret |

The ARN is resolved rather than constructed because Secrets Manager appends six
random characters to the ARN of every secret it creates — the real ones in this
account end `-yJ2Ca1`, `-r8KcNb` and so on. An SSM parameter ARN can be assembled
by hand from the account, region and name; a Secrets Manager ARN cannot.

Write-only arguments need Terraform 1.11, and ephemeral resources need 1.10.
That is why `required_version` is `>= 1.11.0`.

CI asserts the property rather than trusting review: a job fails the build if
anyone reintroduces `data "aws_secretsmanager_secret_version"`,
`data "aws_ssm_parameter"`, `random_password` or a
`resource "aws_secretsmanager_secret_version"`.

### Rotating a secret

```bash
./scripts/bootstrap_parameters.sh dev --rotate jwt-signing-key
```

The script writes a new secret version, labelled `AWSCURRENT`, and prints what to do next. The previous version becomes `AWSPREVIOUS`, so a rollback needs no regeneration. A running ECS task
holds the old value until it is replaced, so any rotation ends with a forced
deployment:

```bash
aws ecs update-service --cluster movie-search-dev-cluster \
  --service api --force-new-deployment
```

The database password has one extra step. Terraform cannot see a write-only
value, so it cannot tell that the secret changed. Increment
`database_password_version` in the environment and apply:

```bash
./scripts/bootstrap_parameters.sh dev --rotate database-password
# then set database_password_version = 2 in environments/dev/main.tf
terraform apply
```

---

## Deploying, step by step

### 1. Check the configuration without touching AWS

These three need no credentials, and they are what the CI workflow runs on every
pull request:

```bash
cd terraform
terraform fmt -check -recursive
terraform init -backend=false
terraform validate
```

### 2. Create the infrastructure

```bash
# Once per environment: write the configuration and the secrets.
./scripts/bootstrap_parameters.sh dev

cd terraform/environments/dev
terraform init
terraform plan -out=dev.tfplan      # no -var flags: it all comes from AWS
terraform apply dev.tfplan
```

The first apply takes roughly fifteen minutes; RDS dominates it. The ECS
services will start and fail their health checks, because no image has been
pushed yet. That is expected, and step 3 fixes it.

### 3. Build and push the images

```bash
cd terraform/environments/dev
eval "$(terraform output -json ecr_repository_urls | \
  python3 -c 'import json,sys; [print(f"{k.upper().replace(\"-\",\"_\")}_REPO={v}") for k,v in json.load(sys.stdin).items()]')"

REGISTRY="${API_REPO%%/*}"
aws ecr get-login-password --region eu-west-1 | docker login --username AWS --password-stdin "$REGISTRY"

TAG="$(git rev-parse --short HEAD)"
docker build -t "$API_REPO:$TAG"       ../../../api
docker build -t "$MCP_SERVER_REPO:$TAG" ../../../mcp-server
docker build -t "$PIPELINE_REPO:$TAG"   ../../../pipeline
docker push "$API_REPO:$TAG"
docker push "$MCP_SERVER_REPO:$TAG"
docker push "$PIPELINE_REPO:$TAG"
```

### 4. Deploy that tag

```bash
terraform apply -var "image_tag=$TAG"
```

### 5. Run the migrations and load the data

The schema is created by Flyway, exactly as it is locally. Run it from a machine
inside the VPC, or through a bastion or a port forward:

```bash
PREFIX=$(terraform output -raw secret_prefix)
DB_USER=movies
DB_PASS=$(aws secretsmanager get-secret-value \
  --secret-id "$PREFIX/database-password" --query SecretString --output text)
DB_HOST=$(terraform output -raw database_endpoint)

docker run --rm -v "$PWD/../../../database/migrations:/flyway/sql:ro" flyway/flyway:11 \
  -url="jdbc:postgresql://${DB_HOST}/movies" -user="$DB_USER" -password="$DB_PASS" migrate
```

Then run the pipeline once as an ECS task. Terraform prints the exact command:

```bash
terraform output -raw pipeline_run_task_command | bash
```

### 6. Check it

```bash
terraform output api_url
curl -s "$(terraform output -raw api_url)/health" | python3 -m json.tool
```

---

## Reading the plan without an AWS account

`terraform plan` reaches AWS to read the current state, so it needs credentials.
`terraform validate` does not, and it still catches a missing variable, a wrong
type, an unknown attribute and a broken reference. The CI workflow therefore
runs `fmt`, `init -backend=false` and `validate` on every pull request, and runs
`plan` only in the delivery workflow, which has a role to assume.

---

## Cost

Every rate below was fetched from the **AWS Price List API** for `us-east-1`, and
every shape is the one the environment's `main.tf` actually declares. On-demand,
730 hours, no savings plan.

The rates the totals are built from:

| Unit | Rate |
| --- | --- |
| Fargate vCPU-hour | $0.04048 |
| Fargate GB-hour | $0.0044450 |
| NAT gateway hour | $0.045 |
| Application Load Balancer hour | $0.0225 |
| Interface VPC endpoint hour | $0.010 |

### dev

| Item | Shape | Per month |
| --- | --- | ---: |
| ECS Fargate | 3 vCPU, 6 GiB — api 0.5/1, mcp 0.5/1, embeddings 2/4 | $108.12 |
| RDS instance | `db.t4g.medium`, single AZ | $47.45 |
| RDS storage | 20 GiB gp3 | $2.30 |
| NAT gateway | 1, shared across both zones | $32.85 |
| Application Load Balancer | 1 | $16.42 |
| Secrets Manager | 4 secrets at $0.40 | $1.60 |
| Interface VPC endpoints | off in dev | — |
| | **Total** | **~$209** |

### prod

| Item | Shape | Per month |
| --- | --- | ---: |
| ECS Fargate | 14 vCPU, 28 GiB — api 1/2 ×3, mcp 1/2 ×3, embeddings 4/8 ×2 | $504.56 |
| RDS instance | `db.r7g.large`, **Multi-AZ** | $348.94 |
| RDS storage | 100 GiB gp3 | $23.00 |
| NAT gateway | 3, one per zone | $98.55 |
| Application Load Balancer | 1 | $16.42 |
| Interface VPC endpoints | 6 services × 3 zones = 18 | $131.40 |
| Secrets Manager | 4 secrets at $0.40 | $1.60 |
| | **Total** | **~$1,124** |

**What these exclude:** data transfer, CloudWatch ingestion and storage, ECR
storage, load balancer LCUs, and per-request charges. They are traffic dependent,
and small next to the fixed hourly costs above. Add roughly $5 to $15 a month in
dev.

### Where the money actually goes

Three observations worth having before you deploy anything.

**The database is the single largest line in production**, at $349 — and $175 of
that is the Multi-AZ standby, which is idle capacity you are paying for so a zone
failure costs nothing. That is the right trade for production and the wrong one
for dev, which is why `database_multi_az` is a variable.

**Compute is not the biggest bill in dev; it is close, but the fixed costs are
what surprise people.** The NAT gateway and the load balancer together are $49 a
month before a single request is served. Both are hourly, both bill whether the
platform is used or not, and neither scales down.

**Interface endpoints cost more than the NAT gateway they save.** In prod, 18
endpoints at $131 exceed the 3 NAT gateways at $99. They earn their place by
keeping image pulls and secret reads off the public internet and by cutting NAT
*data* charges at volume — but at low traffic they are a security purchase, not a
saving. That is why `enable_interface_endpoints` is false in dev.

### Keeping it cheap

- **Destroy it when you are not using it.** The teardown workflow exists for
  exactly this; see [Destroying an environment](#destroying-an-environment). A
  dev environment torn down on Friday and rebuilt on Monday costs about a third.
- **Scale the services to zero** if you want to keep the data. The database and
  the NAT gateway keep billing — about $84 a month — but the $108 of Fargate
  stops.
- **`single_nat_gateway = true`** is already the dev default. Turning it on in
  prod would save $66 a month and reintroduce a single point of failure.
- **The embedding service is the largest compute line**, at 2 of dev's 3 vCPU.
  It is also the throughput bottleneck, so it is the first thing to right-size in
  either direction.

---

## Destroying an environment

```bash
cd terraform/environments/dev
terraform destroy
```

Both stores survive, because Terraform does not own either. Remove them
deliberately when the environment is really gone:

```bash
aws ssm get-parameters-by-path --path /movie-search/dev --recursive \
  --query 'Parameters[].Name' --output text | xargs -n1 aws ssm delete-parameter --name

# A deleted secret keeps its name for a 7 to 30 day recovery window, so
# re-creating the environment inside that window needs the forced form.
aws secretsmanager list-secrets --filters Key=name,Values=movie-search/dev/ \
  --query 'SecretList[].Name' --output text | tr '\t' '\n' |
  xargs -n1 -I{} aws secretsmanager delete-secret --secret-id {} --recovery-window-in-days 7
```

Production refuses: deletion protection is on for both the RDS instance and the
load balancer, and the ECR repositories keep their images. Turning any of that
off is a deliberate, separate change.

---

## Requirements checklist

| Requirement | Where |
| --- | --- |
| Every secret in AWS Secrets Manager, nothing hardcoded | Secrets Manager, injected in `modules/compute` through `secrets` blocks. Nothing is in state either. Non-secret configuration is in Parameter Store, which is free and needs no rotation |
| Compute uses IAM roles, no access keys | `modules/iam`; GitHub Actions authenticates through OIDC |
| RDS in private subnets only | `modules/networking` database tier has no route to a NAT gateway |
| ALB with HTTPS | `modules/alb`; the HTTP listener only redirects to HTTPS |
| Auto-scaling on CPU and memory | `modules/compute`, target tracking policies per service |
| VPC Flow Logs | `modules/networking`, all traffic, to CloudWatch Logs |
| State in S3 with DynamoDB locking | `environments/*/main.tf` backend blocks |
| `Environment`, `Project`, `ManagedBy` tags on everything | `local.common_tags` in `main.tf`, plus provider `default_tags` |
| No secret in the state file | `modules/secrets`; asserted by the CI job "No secret value is read into state" |
