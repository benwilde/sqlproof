"""Child-pytest evidence: assertion failures count, infrastructure failures do not."""

from __future__ import annotations

import json
import os
from collections.abc import Generator
from pathlib import Path
from typing import Any, cast

import pytest
from hypothesis import settings

_tests: dict[str, dict[str, Any]] = {}
_collection_errors = 0


def pytest_configure() -> None:
    _tests.clear()
    global _collection_errors
    _collection_errors = 0
    settings.register_profile(
        "sql_benchmark",
        max_examples=int(os.environ["SQLPROOF_BENCHMARK_EXAMPLES"]),
        deadline=None,
        database=None,
        derandomize=False,
        report_multiple_bugs=False,
    )
    settings.load_profile("sql_benchmark")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        function = getattr(item, "obj", None)
        is_property = hasattr(function, "hypothesis")
        configured = cast(
            Any, getattr(function, "_hypothesis_internal_use_settings", None) or settings()
        )
        if is_property and (
            configured.max_examples != int(os.environ["SQLPROOF_BENCHMARK_EXAMPLES"])
            or configured.database is not None
            or configured.derandomize
            or getattr(function, "_hypothesis_internal_use_seed", None) is not None
        ):
            raise pytest.UsageError(
                "benchmark properties must use the runner's example/seed settings"
            )
        _tests[item.nodeid] = {
            "kind": "property" if is_property else "example",
            "phases": {},
        }


def _assertions_only(error: BaseException) -> bool:
    if isinstance(error, BaseExceptionGroup):
        group = cast(BaseExceptionGroup[BaseException], error)
        return all(_assertions_only(child) for child in group.exceptions)
    return isinstance(error, AssertionError)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[Any]
) -> Generator[None, Any, None]:
    outcome = yield
    report = outcome.get_result()
    if report.passed and not hasattr(report, "wasxfail"):
        status = "passed"
    elif report.skipped or hasattr(report, "wasxfail"):
        status = "skipped"
    elif call.when == "call" and call.excinfo and _assertions_only(call.excinfo.value):
        status = "failed"
    else:
        status = "error"
    evidence: dict[str, str] = {"status": status}
    if call.excinfo:
        evidence["exception"] = call.excinfo.type.__name__
    _tests[item.nodeid]["phases"][call.when] = evidence


def pytest_collectreport(report: pytest.CollectReport) -> None:
    if report.failed:
        global _collection_errors
        _collection_errors += 1


def status_for_phases(phases: dict[str, dict[str, str]]) -> str:
    """Every phase must complete: teardown and fixture errors invalidate a result."""
    statuses = {phase["status"] for phase in phases.values()}
    if "error" in statuses:
        return "error"
    if "skipped" in statuses:
        return "skipped"
    if set(phases) != {"setup", "call", "teardown"}:
        return "error"
    return "failed" if "failed" in statuses else "passed"


def pytest_sessionfinish(exitstatus: int) -> None:
    for test in _tests.values():
        test["status"] = status_for_phases(test["phases"])
    Path(os.environ["SQLPROOF_BENCHMARK_RESULT"]).write_text(
        json.dumps(
            {
                "exit_code": int(exitstatus),
                "collection_errors": _collection_errors,
                "tests": _tests,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
