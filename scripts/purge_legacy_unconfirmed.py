"""Preview or remove pre-v7 unconfirmed rows from Supabase/SQLite.

Usage:
  python scripts/purge_legacy_unconfirmed.py          # dry run
  python scripts/purge_legacy_unconfirmed.py --apply  # destructive
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.repository_v7 import init_v7_schema
from database import db


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Actually delete legacy unconfirmed rows")
    args = parser.parse_args()
    init_v7_schema()
    false_value = "FALSE" if db.USE_POSTGRES else "0"
    with db.db_cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM signals WHERE confirmed={false_value}")
        signal_count = int(cursor.fetchone()[0] or 0)
        cursor.execute(f"SELECT COUNT(*) FROM active_signals WHERE is_confirmed={false_value}")
        active_count = int(cursor.fetchone()[0] or 0)
    print(f"Legacy unconfirmed signals: {signal_count}")
    print(f"Legacy unconfirmed active rows: {active_count}")
    if not args.apply:
        print("DRY RUN only. Re-run with --apply after reviewing your backup.")
        return
    with db.db_cursor() as cursor:
        cursor.execute(f"DELETE FROM active_signals WHERE is_confirmed={false_value}")
        cursor.execute(f"DELETE FROM signals WHERE confirmed={false_value}")
    print("Legacy unconfirmed rows deleted. Confirmed history was not touched.")


if __name__ == "__main__":
    main()
