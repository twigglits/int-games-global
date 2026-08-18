# ---------------------------------------------------------------------------
# The schema, as a runnable image.
#
# Locally, docker-compose mounts database/migrations into the stock Flyway
# image as a volume. That works on one machine and nowhere else: RDS sits in a
# private subnet with no public address, so the only thing that can reach it is
# a task running inside the VPC — and a task cannot mount a directory from a
# GitHub runner.
#
# Baking the SQL into an image makes the migration deployable by the same
# mechanism as every other component: build it, scan it, push it to ECR, run it
# as a Fargate task. It also makes the schema versioned by commit, so the
# migration that ran and the code that expects it come from the same SHA.
# ---------------------------------------------------------------------------
FROM flyway/flyway:11

# Flyway reads every .sql here, in version order, and records what it applied in
# its own history table. Re-running the task is therefore safe: already-applied
# versions are skipped, which is what makes the delivery step idempotent.
COPY migrations /flyway/sql

# URL, user and password arrive as FLYWAY_* environment variables — the password
# from Secrets Manager — so no credential is ever written into this image or
# into a command line.
ENTRYPOINT ["/flyway/flyway"]
CMD ["migrate"]
