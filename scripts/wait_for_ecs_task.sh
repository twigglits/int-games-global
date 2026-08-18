#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Wait for a one-off ECS task to stop, print its log, and exit with the
# container's own exit code.
#
#   ./scripts/wait_for_ecs_task.sh <cluster> <task-arn> <log-group> [timeout]
#
# This exists because `aws ecs wait tasks-stopped` cannot wait long enough. Its
# ceiling is fixed at 100 attempts of 6 seconds — 10 minutes — and the CLI
# offers no way to raise it. The first full pipeline run embeds 3,200 movies and
# took 10m41s, so the waiter gave up 21 seconds before the task finished and the
# delivery step reported a failure for a run that had exited 0 and loaded every
# row. A deployment that works must not be reported as broken.
# ---------------------------------------------------------------------------
set -euo pipefail

CLUSTER="${1:?cluster required}"
TASK_ARN="${2:?task arn required}"
LOG_GROUP="${3:?log group required}"
TIMEOUT="${4:-2400}"   # 40 minutes, comfortably above a cold embedding run

echo "waiting for $TASK_ARN (timeout ${TIMEOUT}s)"

DEADLINE=$(( SECONDS + TIMEOUT ))
STATUS=""
while [ "$SECONDS" -lt "$DEADLINE" ]; do
  STATUS="$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$TASK_ARN" \
    --query 'tasks[0].lastStatus' --output text)"
  [ "$STATUS" = "STOPPED" ] && break
  # Quiet on purpose: a line per poll buries the log that follows.
  sleep 15
done

if [ "$STATUS" != "STOPPED" ]; then
  echo "::error::task did not stop within ${TIMEOUT}s (last status: ${STATUS})"
  aws logs tail "$LOG_GROUP" --since 1h || true
  exit 1
fi

EXIT_CODE="$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$TASK_ARN" \
  --query 'tasks[0].containers[0].exitCode' --output text)"
REASON="$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$TASK_ARN" \
  --query 'tasks[0].stoppedReason' --output text)"

# Always printed, not only on failure: the run report is the useful record of a
# successful pipeline, and going to find it in CloudWatch afterwards is friction.
aws logs tail "$LOG_GROUP" --since 1h || true

echo "task stopped: exit=${EXIT_CODE} reason=${REASON}"
test "$EXIT_CODE" = "0"
