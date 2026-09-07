"""Seed demo data into the deployed stack and exercise the weekly reflection.

Writes a demo account and a fortnight of back-dated journal entries straight
into the stack's DynamoDB tables, then (optionally) invokes the deployed
scheduled-reflection Lambda so the automatic weekly reflection can be
demonstrated without waiting seven days for EventBridge to fire.

Table names come from the CloudFormation stack outputs, so nothing is
hardcoded and no throwaway tables are created.

Entries carry preset moods and are written directly to DynamoDB, which means
seeding costs ZERO Gemini API calls. Creating the same entries through
POST /entries would classify each one and exhaust the 20/day free tier.

Usage (from the project root, with the venv active):

    python scripts/seed_demo_data.py                      # seed only
    python scripts/seed_demo_data.py --invoke-scheduled   # seed + run the Lambda
    python scripts/seed_demo_data.py --show               # read reflections back
    python scripts/seed_demo_data.py --cleanup            # remove the demo account

--cleanup deletes only the demo account's own items. It never touches the
tables themselves - those belong to the CloudFormation stack.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

# Lambda unpacks the bundle with "models", "services" etc. at the top level.
BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import boto3  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402

DEFAULT_STACK = "moodjournal-stack"
DEMO_USERNAME = "demo.user"
DEMO_PASSWORD = "DemoPass123"

# A deliberate arc - a good start, a stressful stretch, then recovery - so the
# trend chart and the reflection have a real pattern to describe.
SEED_ENTRIES: list[tuple[int, str, str, str]] = [
    (13, "POSITIVE", "Fresh start", "Felt happy and motivated setting up the new project."),
    (12, "POSITIVE", "Good progress", "Pleased with how much I got through today."),
    (11, "NEUTRAL", "Ordinary day", "Worked, ate, went home. Nothing much to report."),
    (10, "ANXIOUS", "Deadline looming", "Worried about whether this will be finished in time."),
    (9, "ANXIOUS", "Still on edge", "Feeling tense and uncertain about the next step."),
    (8, "NEGATIVE", "Rough one", "Frustrated and tired after everything broke at once."),
    (7, "NEGATIVE", "Low", "Disappointed with how little I managed today."),
    (6, "NEUTRAL", "Reset", "Took the day slowly and caught up on reading."),
    (5, "POSITIVE", "Breakthrough", "Great feeling when it finally worked."),
    (4, "POSITIVE", "Momentum", "Excited about the progress, feeling confident again."),
    (3, "NEUTRAL", "Admin day", "Paperwork and email. Fine, just unremarkable."),
    (2, "ANXIOUS", "Nerves", "Nervous about presenting this and being asked hard questions."),
    (1, "POSITIVE", "Prepared", "Glad I practised, feeling much more relaxed now."),
    (0, "POSITIVE", "Nearly there", "Proud of how far this has come in two weeks."),
]

CONFIDENCE = 0.9


def stack_outputs(stack_name: str, region: str) -> dict[str, str]:
    """Read the CloudFormation outputs, so no resource name is hardcoded."""
    cfn = boto3.client("cloudformation", region_name=region)
    try:
        stacks = cfn.describe_stacks(StackName=stack_name)["Stacks"]
    except ClientError as exc:
        raise SystemExit(
            f"Could not read stack '{stack_name}' in {region}: {exc}\n"
            "Deploy it first with: sam deploy --guided"
        ) from exc
    return {o["OutputKey"]: o["OutputValue"] for o in stacks[0].get("Outputs", [])}


def seed(days_back_limit: int) -> str:
    """Create the demo account and its back-dated entries. Returns the userId."""
    from models.journal_entry import JournalEntry
    from models.user import User
    from repositories.journal_repository import JournalRepository
    from repositories.user_repository import UsernameTakenError, UserRepository
    from utils.passwords import hash_password

    users = UserRepository()
    journals = JournalRepository()

    user = users.find_by_username(DEMO_USERNAME)
    if user is not None:
        print(f"  reusing existing account {DEMO_USERNAME} ({user.user_id})")
    else:
        user = User(username=DEMO_USERNAME, password_hash=hash_password(DEMO_PASSWORD))
        try:
            users.create(user)
        except UsernameTakenError:
            user = users.find_by_username(DEMO_USERNAME)
        print(f"  created account {DEMO_USERNAME} / {DEMO_PASSWORD} ({user.user_id})")

    today = datetime.now(timezone.utc).date()
    written = 0
    for days_ago, mood, title, content in SEED_ENTRIES:
        if days_ago > days_back_limit:
            continue
        entry_date = (today - timedelta(days=days_ago)).isoformat()
        # A deterministic id keeps the script re-runnable: re-seeding overwrites
        # the same entry instead of adding a duplicate with a fresh UUID.
        entry_id = str(uuid5(NAMESPACE_URL, f"moodjournal-demo/{user.user_id}/{entry_date}"))
        journals.put_entry(
            JournalEntry(
                user_id=user.user_id,
                title=title,
                content=content,
                entry_date=entry_date,
                mood=mood,
                confidence=CONFIDENCE,
                short_reason="Seeded demo data; not classified by Gemini.",
                classification_fallback=False,
                entry_id=entry_id,
            )
        )
        written += 1

    print(f"  wrote {written} entries across the last {days_back_limit + 1} days (0 Gemini calls)")
    return user.user_id


def scheduled_function_name(stack_name: str, region: str) -> str:
    """Resolve the deployed Lambda's real name from the stack.

    The name is derived from the Environment parameter, which is not a stack
    output, so asking CloudFormation for the resource is more reliable than
    reconstructing it and guessing wrong on a non-dev deployment.
    """
    cfn = boto3.client("cloudformation", region_name=region)
    resource = cfn.describe_stack_resource(
        StackName=stack_name, LogicalResourceId="ScheduledReflectionFunction"
    )["StackResourceDetail"]
    return resource["PhysicalResourceId"]


def invoke_scheduled_reflection(function_name: str, region: str) -> None:
    """Invoke the deployed Lambda exactly as EventBridge would.

    This runs the real deployed function under its own IAM role, rather than
    the local copy of the code, so it proves the deployed path end to end.
    """
    client = boto3.client("lambda", region_name=region)
    print(f"  invoking {function_name} ...")

    response = client.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps({"source": "aws.events", "detail-type": "Scheduled Event"}),
    )

    payload = response["Payload"].read().decode("utf-8")
    if response.get("FunctionError"):
        print(f"  Lambda reported an error: {payload}")
        raise SystemExit(1)
    print(f"  returned: {payload}")


def show(user_id: str | None = None) -> None:
    """Print the reflections stored for the demo account."""
    from repositories.journal_repository import JournalRepository
    from repositories.user_repository import UserRepository

    if user_id is None:
        user = UserRepository().find_by_username(DEMO_USERNAME)
        if user is None:
            print("  no demo account found")
            return
        user_id = user.user_id

    reflections, _ = JournalRepository().list_reflections(user_id, limit=10)
    if not reflections:
        print("  no reflections stored yet")
        return

    for reflection in reflections:
        print()
        print(f"  period      : {reflection.period} "
              f"({reflection.period_start} to {reflection.period_end})")
        print(f"  entries used: {reflection.entry_count}")
        print(f"  generated by: {reflection.generated_by}")
        print(f"  created at  : {reflection.created_at}")
        print(f"  summary     : {reflection.summary}")


def cleanup() -> None:
    """Remove the demo account and everything it owns.

    Deletes items only. The tables belong to the CloudFormation stack and are
    left alone - use `sam delete` to remove those.
    """
    from boto3.dynamodb.conditions import Key
    from repositories.user_repository import UserRepository

    user = UserRepository().find_by_username(DEMO_USERNAME)
    if user is None:
        print("  no demo account found")
        return

    dynamodb = boto3.resource("dynamodb", region_name=os.environ["AWS_REGION"])
    table = dynamodb.Table(os.environ["DYNAMODB_TABLE_NAME"])

    # Entries and reflections share one partition, so one query finds them all.
    removed = 0
    start_key = None
    while True:
        params: dict = {"KeyConditionExpression": Key("PK").eq(f"USER#{user.user_id}")}
        if start_key:
            params["ExclusiveStartKey"] = start_key
        response = table.query(**params)
        with table.batch_writer() as batch:
            for item in response.get("Items", []):
                batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})
                removed += 1
        start_key = response.get("LastEvaluatedKey")
        if not start_key:
            break

    dynamodb.Table(os.environ["USERS_TABLE_NAME"]).delete_item(Key={"userId": user.user_id})
    print(f"  deleted the demo account and {removed} of its items")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack-name", default=DEFAULT_STACK)
    parser.add_argument("--region", help="defaults to the configured CLI region")
    parser.add_argument("--days", type=int, default=13, help="days of history to seed")
    parser.add_argument("--invoke-scheduled", action="store_true",
                        help="invoke the deployed weekly-reflection Lambda afterwards")
    parser.add_argument("--show", action="store_true", help="print stored reflections and exit")
    parser.add_argument("--cleanup", action="store_true", help="remove the demo account and exit")
    args = parser.parse_args()

    region = args.region or boto3.session.Session().region_name
    if not region:
        raise SystemExit("No region configured. Pass --region.")

    outputs = stack_outputs(args.stack_name, region)
    journal_table = outputs.get("JournalTableName")
    users_table = outputs.get("UsersTableName")
    if not journal_table or not users_table:
        raise SystemExit("Stack outputs are missing JournalTableName / UsersTableName.")

    # The repositories read these at import time, so set them before importing.
    os.environ["AWS_REGION"] = region
    os.environ["AWS_DEFAULT_REGION"] = region
    os.environ["DYNAMODB_TABLE_NAME"] = journal_table
    os.environ["USERS_TABLE_NAME"] = users_table

    print(f"stack : {args.stack_name} ({region})")
    print(f"tables: {journal_table}, {users_table}")

    if args.cleanup:
        print("\n[cleanup]")
        cleanup()
        return 0

    if args.show:
        print("\n[reflections]")
        show()
        return 0

    print("\n[1/3] seeding")
    user_id = seed(args.days)

    if args.invoke_scheduled:
        print("\n[2/3] invoking the deployed weekly reflection")
        invoke_scheduled_reflection(scheduled_function_name(args.stack_name, region), region)

        print("\n[3/3] reflections now stored")
        show(user_id)
    else:
        print("\nSeeded. To generate the weekly reflection now, re-run with --invoke-scheduled")

    print(f"\nSign in as {DEMO_USERNAME} / {DEMO_PASSWORD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
