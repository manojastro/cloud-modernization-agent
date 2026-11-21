"""Seed the estate database: python -m simulator [--size N] [--no-reset]"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the simulated application estate")
    parser.add_argument("--size", type=int, default=None, help="Number of applications")
    parser.add_argument("--no-reset", action="store_true", help="Do not drop existing tables first")
    args = parser.parse_args()

    from app.db import init_db, session_scope
    from simulator.loader import seed_estate

    init_db()
    with session_scope() as session:
        counts = seed_estate(session, size=args.size, reset=not args.no_reset)

    print("Estate seeded:")
    for key in ("applications", "shared_services", "servers", "network_flows",
                "file_transfers", "batch_jobs", "cmdb_records", "truth_edges_written"):
        print(f"  {key}: {counts[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
