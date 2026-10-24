"""Wipe test data so you can start a fresh test run. Keeps users and Twilio numbers.

Dry run by default (counts only). Nothing is deleted without --yes.

    cd backend
    python scripts/reset_test_data.py                    # show what would be deleted
    python scripts/reset_test_data.py --yes              # delete it
    python scripts/reset_test_data.py --yes --include-projects

Documents are removed with delete_many({}), so collections and their indexes (including the
unique lead_research.contact_id index) stay in place. Restart the backend afterwards: live
call state is held in memory and is not touched by this script.
"""

import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

from pymongo import MongoClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import get_settings  # noqa: E402  (needs the sys.path line above)

KEEP = {"users", "twilio_numbers"}
ALWAYS_DELETE = ["call_logs", "contacts", "clients", "lead_research"]
# The case-study library is slow to rebuild (each upload is AI-processed), so it is opt-in.
OPT_IN = {"projects": "--include-projects"}


def describe_target(uri: str, db_name: str) -> str:
    host = urlparse(uri).hostname or "unknown-host"  # drops any user:password from the URI
    return f"{host} / database '{db_name}'"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--yes", action="store_true", help="actually delete (default is a dry run)")
    parser.add_argument("--include-projects", action="store_true", help="also clear the projects collection")
    args = parser.parse_args()

    settings = get_settings()
    client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=5000)
    db = client[settings.mongo_db_name]
    print(f"Target: {describe_target(settings.mongo_uri, settings.mongo_db_name)}")

    existing = set(db.list_collection_names())
    targets = list(ALWAYS_DELETE)
    if args.include_projects:
        targets.append("projects")

    print(f"\n{'collection':<16} {'action':<8} documents")
    for name in sorted(existing | set(targets)):
        count = db[name].count_documents({}) if name in existing else 0
        if name in KEEP:
            action = "KEEP"
        elif name in targets:
            action = "DELETE"
        elif name in OPT_IN:
            action = f"keep ({OPT_IN[name]} to clear)"
        else:
            action = "keep (unknown)"
        print(f"{name:<16} {action:<8} {count}")

    unknown = existing - KEEP - set(ALWAYS_DELETE) - set(OPT_IN)
    if unknown:
        print(f"\nNote: collections this script does not know about were left alone: {sorted(unknown)}")

    if not args.yes:
        print("\nDry run only. Re-run with --yes to delete the DELETE rows above.")
        return 0

    print()
    for name in targets:
        if name in existing:
            result = db[name].delete_many({})
            print(f"deleted {result.deleted_count:>6} from {name}")
    print("\nDone. Restart the backend so no stale in-memory call state remains.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
