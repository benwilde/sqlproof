"""Curated SQL faults, fresh clones, and per-test fail-on-bug/pass-on-correct scoring."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from typing import Any
from uuid import uuid4

import hypothesis

from sqlproof import _database as database
from sqlproof import _dsn as conninfo
from sqlproof._version import __version__
from sqlproof.mutation.apply import prepare_mutants
from sqlproof.mutation.model import Mutant, MutationSet, Replace
from sqlproof.mutation.persist import capture_git_info
from sqlproof.mutation.runner import LocalMutationRunner

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent


class BenchmarkError(Exception):
    pass


def score(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Only matching, baseline-green tests can earn credit for an assertion failure."""
    before = baseline.get("tests", {})
    after = candidate.get("tests", {})
    if not before or baseline.get("exit_code") != 0 or baseline.get("collection_errors"):
        return {"status": "error", "reason": "invalid baseline", "properties": {}}
    if any(test["status"] != "passed" for test in before.values()):
        return {"status": "error", "reason": "baseline did not pass every test", "properties": {}}
    if set(before) != set(after):
        return {"status": "error", "reason": "test collection changed", "properties": {}}
    properties = {node: test["status"] for node, test in after.items()}
    if (
        candidate.get("collection_errors")
        or candidate.get("exit_code") not in (0, 1)
        or any(status not in ("passed", "failed") for status in properties.values())
    ):
        return {
            "status": "error",
            "reason": "incomplete or errored execution",
            "properties": properties,
        }
    caught = any(status == "failed" for status in properties.values())
    if candidate["exit_code"] != int(caught):
        return {
            "status": "error",
            "reason": "exit code disagrees with test evidence",
            "properties": properties,
        }
    return {"status": "caught" if caught else "survived", "properties": properties}


def summarize(tasks: list[dict[str, Any]], seeds: list[int]) -> dict[str, Any]:
    outcomes = [fault for task in tasks for run in task["runs"] for fault in run["faults"]]
    errors = sum(fault["status"] == "error" for fault in outcomes)
    caught = sum(fault["status"] == "caught" for fault in outcomes)
    complete = bool(tasks) and all(
        [run["seed"] for run in task["runs"]] == seeds
        and all(
            [fault["id"] for fault in run["faults"]] == task["fault_ids"] for run in task["runs"]
        )
        for task in tasks
    )
    reliable = sum(
        bool(task["runs"])
        and all(
            next(f for f in run["faults"] if f["id"] == fault_id)["status"] == "caught"
            for run in task["runs"]
        )
        for task in tasks
        for fault_id in task["fault_ids"]
    )
    faults = sum(len(task["fault_ids"]) for task in tasks)
    valid = complete and bool(outcomes) and not errors
    return {
        "valid": valid,
        "complete": complete,
        "faults": faults,
        "seeds": seeds,
        "evaluations": len(outcomes),
        "caught": caught,
        "survived": len(outcomes) - caught - errors,
        "errors": errors,
        "recall": caught / len(outcomes) if valid else None,
        "caught_on_every_seed": reliable,
        "reliable_recall": reliable / faults if valid else None,
    }


class PropertyRunner(LocalMutationRunner):
    """Reuse mutation cloning, replacing suite-only output with structured test evidence."""

    def __init__(
        self,
        *,
        database_url: str,
        maintenance_db: str,
        suite: Path,
        seed: int,
        examples: int,
        timeout_s: float,
    ) -> None:
        super().__init__(
            database_url=database_url,
            maintenance_db=maintenance_db,
            pytest_args=[],
            hypothesis_seed=seed,
            timeout_s=timeout_s,
        )
        self.suite = suite
        self.examples = examples
        self.evidence: dict[str, Any] = {}

    def _run_pytest(self, clone_dsn: str) -> tuple[int, str]:
        self.evidence = {}
        with tempfile.TemporaryDirectory(prefix="sqlproof-benchmark-") as tmp:
            result_path = Path(tmp) / "results.json"
            env = dict(os.environ)
            env.pop("PYTEST_ADDOPTS", None)
            env.pop("SQLPROOF_BENCHMARK_DATABASE_URL", None)
            env.update(
                {
                    "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                    "PYTHONPATH": os.pathsep.join([str(REPO), str(REPO / "src")]),
                    "SQLPROOF_DATABASE_URL": clone_dsn,
                    "SQLPROOF_TEST_DATABASE_URL": clone_dsn,
                    "SUPABASE_DB_URL": clone_dsn,
                    "SQLPROOF_BENCHMARK_RESULT": str(result_path),
                    "SQLPROOF_BENCHMARK_EXAMPLES": str(self.examples),
                }
            )
            command = [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-o",
                "addopts=",
                "-p",
                "sqlproof.pytest_plugin",
                "-p",
                "_hypothesis_pytestplugin",
                "-p",
                "benchmarks.sql.plugin",
                f"--hypothesis-seed={self.hypothesis_seed}",
                f"--rootdir={self.suite.parent}",
                f"--confcutdir={self.suite.parent}",
                str(self.suite),
            ]
            process = subprocess.run(
                command,
                env=env,
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
                check=False,
            )
            if result_path.exists():
                self.evidence = json.loads(result_path.read_text(encoding="utf-8"))
                if self.evidence.get("exit_code") != process.returncode:
                    self.evidence["collection_errors"] = 1
                    self.evidence["error"] = "pytest exit code disagrees with reported evidence"
            return process.returncode, "benchmark subprocess did not complete cleanly"


def suite_hashes(suite_dir: Path) -> dict[str, str]:
    return {
        str(p.relative_to(suite_dir)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(suite_dir.rglob("*.py"))
    }


@contextmanager
def template(database_url: str, task: str) -> Generator[tuple[str, str]]:
    """Only create/drop uniquely named benchmark databases; never change the supplied DB."""
    maintenance = conninfo.conninfo_to_dict(database_url).get("dbname")
    if not maintenance:
        raise BenchmarkError("the maintenance database URL must specify a database name")
    name = f"sqlproof_bench_{task}_{uuid4().hex[:16]}"
    quoted = conninfo.quote_identifier(name)
    with database.connect(database_url, autocommit=True) as admin:
        roles = admin.execute(
            "SELECT rolname FROM pg_roles WHERE rolname IN ('authenticated', 'anon') "
            "AND NOT rolsuper AND NOT rolbypassrls"
        ).fetchall()
        if {row[0] for row in roles} != {"authenticated", "anon"}:
            raise BenchmarkError("benchmark needs non-superuser authenticated and anon roles")
        admin.execute(f"CREATE DATABASE {quoted} TEMPLATE template0")
    try:
        dsn = conninfo.make_conninfo(database_url, dbname=name)
        with database.connect(dsn, autocommit=True) as connection:
            connection.execute((ROOT / "common.sql").read_text(encoding="utf-8"))
            connection.execute((ROOT / "tasks" / task / "schema.sql").read_text(encoding="utf-8"))
        yield dsn, maintenance
    finally:
        with database.connect(database_url, autocommit=True) as admin:
            admin.execute(f"DROP DATABASE IF EXISTS {quoted} WITH (FORCE)")


def run_benchmark(
    *,
    database_url: str,
    seeds: list[int],
    examples: int = 40,
    suite_dir: Path = ROOT / "reference",
    tasks: list[str] | None = None,
    timeout_s: float = 120,
) -> dict[str, Any]:
    if not seeds or len(set(seeds)) != len(seeds) or any(not 0 <= seed < 2**32 for seed in seeds):
        raise BenchmarkError("supply distinct seeds in range 0..2**32-1")
    if examples < 1 or not isfinite(timeout_s) or timeout_s <= 0:
        raise BenchmarkError("examples and timeout must be positive")
    catalog = json.loads((ROOT / "faults.json").read_text(encoding="utf-8"))
    selected = list(catalog) if tasks is None else tasks
    if (
        not selected
        or len(set(selected)) != len(selected)
        or any(t not in catalog for t in selected)
    ):
        raise BenchmarkError("select distinct known tasks")
    suite_dir = suite_dir.resolve()
    for task in selected:
        if not (suite_dir / f"test_{task}.py").is_file():
            raise BenchmarkError(f"suite is missing test_{task}.py")
    git_sha, dirty = capture_git_info()
    with database.connect(database_url, autocommit=True) as connection:
        server_version = connection.execute("SHOW server_version").fetchone()[0]
    report: dict[str, Any] = {
        "format_version": 1,
        "benchmark": "sqlproof-sql-properties-v1",
        "started_at": datetime.now(UTC).isoformat(),
        "git_sha": git_sha,
        "git_dirty": dirty,
        "sqlproof_version": __version__,
        "python_version": sys.version.split()[0],
        "hypothesis_version": hypothesis.__version__,
        "postgres_version": server_version,
        "examples": examples,
        "timeout_s": timeout_s,
        "suite_hashes": suite_hashes(suite_dir),
        "common_sha256": hashlib.sha256((ROOT / "common.sql").read_bytes()).hexdigest(),
        "harness_hashes": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in ("runner.py", "plugin.py")
        },
        "catalog_sha256": hashlib.sha256((ROOT / "faults.json").read_bytes()).hexdigest(),
        "tasks": [],
    }
    for task in selected:
        schema_sql = (ROOT / "tasks" / task / "schema.sql").read_text(encoding="utf-8")
        faults = catalog[task]
        prepared = prepare_mutants(
            MutationSet(
                tuple(
                    Mutant("function", fault["target"], (Replace(fault["old"], fault["new"]),))
                    for fault in faults
                )
            ),
            schema_sql,
        )
        task_report: dict[str, Any] = {
            "id": task,
            "schema_sha256": hashlib.sha256(schema_sql.encode()).hexdigest(),
            "contract_sha256": hashlib.sha256(
                (ROOT / "tasks" / task / "contract.md").read_bytes()
            ).hexdigest(),
            "fault_ids": [fault["id"] for fault in faults],
            "runs": [],
        }
        report["tasks"].append(task_report)
        with template(database_url, task) as (dsn, maintenance):
            for seed in seeds:
                runner = PropertyRunner(
                    database_url=dsn,
                    maintenance_db=maintenance,
                    suite=suite_dir / f"test_{task}.py",
                    seed=seed,
                    examples=examples,
                    timeout_s=timeout_s,
                )
                try:
                    runner.run_baseline()
                except Exception as exc:
                    runner.evidence = {"error": type(exc).__name__}
                baseline = runner.evidence
                run: dict[str, Any] = {"seed": seed, "baseline": baseline, "faults": []}
                task_report["runs"].append(run)
                baseline_ok = score(baseline, baseline)["status"] == "survived"
                for fault, mutant in zip(faults, prepared, strict=True):
                    runner.evidence = {}
                    duration = None
                    runner_failed = False
                    if baseline_ok:
                        outcome = runner.run((mutant,)).outcomes[0]
                        duration = outcome.duration_s
                        runner_failed = outcome.status == "error"
                    result = score(baseline, runner.evidence)
                    if runner_failed:
                        result.update(status="error", reason="mutation runner failed")
                    run["faults"].append(
                        {
                            "id": fault["id"],
                            "mutant_id": mutant.mutant_id,
                            "trigger": fault["trigger"],
                            "duration_s": duration,
                            "execution": runner.evidence,
                            **result,
                        }
                    )
    report["summary"] = summarize(report["tasks"], seeds)
    if suite_hashes(suite_dir) != report["suite_hashes"]:
        report["summary"].update(valid=False, recall=None, reliable_recall=None)
        report["error"] = "suite files changed during the benchmark"
    return report
