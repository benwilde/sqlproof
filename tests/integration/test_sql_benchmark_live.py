"""The reference suite and negative controls exercise real clone-and-score runs."""

import os

import pytest

from benchmarks.sql.runner import run_benchmark

pytestmark = pytest.mark.skipif(
    "SQLPROOF_TEST_DATABASE_URL" not in os.environ,
    reason="set SQLPROOF_TEST_DATABASE_URL to run Postgres integration tests",
)


@pytest.mark.parametrize("task", ["totals", "pricing", "visibility", "migration"])
def test_reference_properties_detect_each_known_fault(task):
    report = run_benchmark(
        database_url=os.environ["SQLPROOF_TEST_DATABASE_URL"], seeds=[0], tasks=[task], examples=25
    )
    assert report["summary"]["valid"], report
    assert report["summary"]["caught_on_every_seed"] == 3, report
    assert report["summary"]["survived"] == 0, report
    runs = report["tasks"][0]["runs"]
    assert all(
        any(status == "failed" for status in fault["properties"].values())
        for run in runs
        for fault in run["faults"]
    )


@pytest.mark.parametrize(
    "body, expected, timeout",
    [
        ("def test_nothing():\n    pass\n", "survived", 120),
        ("def test_false():\n    assert False\n", "error", 120),
        ("import pytest\n@pytest.mark.skip\ndef test_skipped():\n    pass\n", "error", 120),
        ("raise ImportError('collection failed')\n", "error", 120),
        ("import time\ntime.sleep(5)\ndef test_wait():\n    pass\n", "error", 0.2),
    ],
)
def test_vacuous_or_invalid_suites_cannot_get_a_perfect_score(tmp_path, body, expected, timeout):
    (tmp_path / "test_pricing.py").write_text(body)
    report = run_benchmark(
        database_url=os.environ["SQLPROOF_TEST_DATABASE_URL"],
        seeds=[0],
        tasks=["pricing"],
        suite_dir=tmp_path,
        examples=5,
        timeout_s=timeout,
    )
    assert {fault["status"] for fault in report["tasks"][0]["runs"][0]["faults"]} == {expected}
    assert report["summary"]["recall"] == (0 if expected == "survived" else None)
