from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

from benchmarks.sql.runner import ROOT, BenchmarkError, run_benchmark
from sqlproof import _database as database
from sqlproof.exceptions import SqlProofMutationError


def main() -> int:
    parser = argparse.ArgumentParser(description="Score SQL properties against curated faults")
    parser.add_argument("--suite-dir", type=Path, default=ROOT / "reference")
    parser.add_argument(
        "--task", action="append", choices=["totals", "pricing", "visibility", "migration"]
    )
    parser.add_argument("--seed", type=int, action="append", help="repeat for several seeds")
    parser.add_argument("--examples", type=int, default=40)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if args.output is not None and args.output.exists():
        parser.error("output file already exists; choose a new path")
    dsn = os.environ.get("SQLPROOF_BENCHMARK_DATABASE_URL")
    if not dsn:
        parser.error("set SQLPROOF_BENCHMARK_DATABASE_URL to a maintenance database")
    try:
        report = run_benchmark(
            database_url=dsn,
            suite_dir=args.suite_dir,
            seeds=args.seed or [0, 1, 42],
            examples=args.examples,
            tasks=args.task,
            timeout_s=args.timeout,
        )
    except BenchmarkError as exc:
        parser.error(str(exc))
    except (database.Error, SqlProofMutationError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"benchmark setup failed ({type(exc).__name__}); no score produced\n")
    output = args.output or Path(".sqlproof/benchmarks") / f"{uuid4().hex}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as file:
        json.dump(report, file, indent=2)
    summary = report["summary"]
    print(
        f"{summary['caught']}/{summary['evaluations']} fault evaluations caught; "
        f"{summary['survived']} survived; {summary['errors']} errors"
    )
    print(f"Report: {output}")
    if not summary["valid"]:
        return 2
    return 0 if not summary["survived"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
