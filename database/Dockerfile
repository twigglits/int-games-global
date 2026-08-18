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
FROM flyway/flyway:13.3.0

# Flyway reads every .sql here, in version order, and records what it applied in
# its own history table. Re-running the task is therefore safe: already-applied
# versions are skipped, which is what makes the delivery step idempotent.
COPY migrations /flyway/sql

# Remove the four database integrations that carry known vulnerabilities.
#
# This is a fix, not a suppression. Scanning the stock image found 16 fixable
# HIGH vulnerabilities, and every one of them lived in a driver for a database
# this platform does not use:
#
#   drivers/couchbase/core-io-3.12.0.jar     8  (bundled netty)
#   drivers/databricks-jdbc-3.4.1.jar        5  (bundled jackson, httpcore)
#   drivers/cassandra/httpcore5-5.4.2.jar    1
#   drivers/cassandra/httpcore5-h2-5.4.jar   1
#   drivers/mssql-jdbc-12.10.2.jre11.jar     1
#
# Deleting the driver alone is not enough, and fails loudly rather than
# silently: Flyway's plugin loader instantiates every database plugin on
# start-up, so a plugin whose driver has gone throws NoClassDefFoundError
# before it reaches the first migration. Each driver is therefore removed
# together with the plugin that loads it.
#
# The remaining 46 plugins, PostgreSQL included, are untouched.
#
# If this platform ever adds one of these engines, restore the pair and its CVEs
# become a decision to make rather than one inherited from a base image.
RUN rm -rf /flyway/drivers/cassandra \
           /flyway/drivers/couchbase \
           /flyway/drivers/databricks-jdbc-*.jar \
           /flyway/drivers/mssql-jdbc-*.jar \
           /flyway/lib/flyway/flyway-database-cassandra-*.jar \
           /flyway/lib/flyway/flyway-database-nc-cassandra-*.jar \
           /flyway/lib/flyway/flyway-database-nc-couchbase-*.jar \
           /flyway/lib/flyway/flyway-database-databricks-*.jar \
           /flyway/lib/flyway/flyway-sqlserver-*.jar

# Non-root, like every other image here. The other Dockerfiles create an `app`
# user at uid 1000; this base already has one there (`ubuntu`), so creating a
# second would collide on the uid. Reusing it gets the same result — uid 1000,
# no root — without an extra layer. Trivy DS-0002 enforces this, and caught the
# first version of this file, which had no USER at all.
USER 1000:1000

# URL, user and password arrive as FLYWAY_* environment variables — the password
# from Secrets Manager — so no credential is ever written into this image or
# into a command line.
ENTRYPOINT ["/flyway/flyway"]
CMD ["migrate"]
