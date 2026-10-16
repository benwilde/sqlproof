"""Benchmark credit requires baseline-green assertions and complete execution evidence."""

import json
from copy import deepcopy

import pytest

from benchmarks.sql import __main__ as cli
from benchmarks.sql import plugin
from benchmarks.sql.runner import ROOT, BenchmarkError, run_benchmark, score, summarize
from sqlproof.mutation.apply import prepare_mutants
from sqlproof.mutation.model import Mutant, MutationSet, Replace


def _evidence(**statuses):
    return {
        "exit_code": int("failed" in statuses.values()),
        "collection_errors": 0,
        "tests": {name: {"status": status} for name, status in statuses.items()},
    }


def test_only_the_property_that_fails_on_the_fault_gets_credit():
    baseline = _evidence(ownership="passed", totals="passed")
    result = score(baseline, _evidence(ownership="passed", totals="failed"))
    assert result == {"status": "caught", "properties": {"ownership": "passed", "totals": "failed"}}


def test_a_fault_that_every_property_accepts_survives():
    baseline = _evidence(total="passed")
    assert score(baseline, baseline)["status"] == "survived"


@pytest.mark.parametrize(
    "options",
    [
        {"seeds": []},
        {"seeds": [0, 0]},
        {"seeds": [-1]},
        {"seeds": [2**32]},
        {"examples": 0},
        {"timeout_s": 0},
        {"timeout_s": float("nan")},
        {"tasks": ["unknown"]},
    ],
)
def test_invalid_benchmark_arguments_are_rejected_before_connecting(options, monkeypatch):
    def should_not_connect(*args, **kwargs):
        pytest.fail("invalid arguments must not touch the database")

    monkeypatch.setattr("benchmarks.sql.runner.database.connect", should_not_connect)
    arguments = {"database_url": "unused", "seeds": [0], **options}
    with pytest.raises(BenchmarkError):
        run_benchmark(**arguments)


@pytest.mark.parametrize("valid,survived,expected", [(True, 0, 0), (True, 1, 1), (False, 0, 2)])
def test_cli_exit_codes_distinguish_detection_survivors_and_errors(
    tmp_path, monkeypatch, valid, survived, expected
):
    report = {
        "summary": {
            "valid": valid,
            "survived": survived,
            "caught": 1,
            "evaluations": 2,
            "errors": 0 if valid else 1,
        }
    }
    output = tmp_path / "run.json"
    monkeypatch.setenv("SQLPROOF_BENCHMARK_DATABASE_URL", "unused")
    monkeypatch.setattr("sys.argv", ["benchmark", "--output", str(output)])
    monkeypatch.setattr(cli, "run_benchmark", lambda **kwargs: report)
    assert cli.main() == expected
    assert json.loads(output.read_text()) == report


def test_an_existing_report_is_not_overwritten(tmp_path, monkeypatch):
    output = tmp_path / "run.json"
    output.write_text("keep this report")
    monkeypatch.setattr("sys.argv", ["benchmark", "--output", str(output)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    assert output.read_text() == "keep this report"


@pytest.mark.parametrize("status", ["failed", "error", "skipped"])
def test_a_non_green_baseline_never_earns_credit(status):
    assert score(_evidence(total=status), _evidence(total="failed"))["status"] == "error"


@pytest.mark.parametrize("status", ["error", "skipped"])
def test_an_execution_error_invalidates_a_run_even_if_another_property_fails(status):
    baseline = _evidence(total="passed", owner="passed")
    assert score(baseline, _evidence(total="failed", owner=status))["status"] == "error"


@pytest.mark.parametrize("exit_code", [2, 3, 4, 5, -9])
def test_interruptions_usage_errors_and_empty_collection_do_not_count_as_detection(exit_code):
    faulty = _evidence(total="failed")
    faulty["exit_code"] = exit_code
    assert score(_evidence(total="passed"), faulty)["status"] == "error"


def test_missing_or_changed_tests_invalidate_attribution():
    baseline = _evidence(total="passed")
    assert score(baseline, _evidence(other="failed"))["status"] == "error"
    assert score(baseline, {})["status"] == "error"
    assert score({}, _evidence(other="failed"))["status"] == "error"


def test_a_collection_error_invalidates_otherwise_complete_results():
    faulty = _evidence(total="failed")
    faulty["collection_errors"] = 1
    assert score(_evidence(total="passed"), faulty)["status"] == "error"


def test_a_false_exit_code_cannot_disguise_an_execution_problem():
    faulty = _evidence(total="failed")
    faulty["exit_code"] = 0
    assert score(_evidence(total="passed"), faulty)["status"] == "error"


def test_reliable_detection_requires_every_requested_seed():
    tasks = [
        {
            "fault_ids": ["a", "b"],
            "runs": [
                {
                    "seed": 0,
                    "faults": [{"id": "a", "status": "caught"}, {"id": "b", "status": "caught"}],
                },
                {
                    "seed": 1,
                    "faults": [{"id": "a", "status": "caught"}, {"id": "b", "status": "survived"}],
                },
            ],
        }
    ]
    summary = summarize(tasks, [0, 1])
    assert summary["recall"] == 0.75
    assert summary["reliable_recall"] == 0.5
    broken = deepcopy(tasks)
    broken[0]["runs"][1]["faults"][1]["status"] = "error"
    invalid = summarize(broken, [0, 1])
    assert invalid["evaluations"] == 4 and invalid["errors"] == 1
    assert not invalid["valid"] and invalid["recall"] is None
    assert invalid["reliable_recall"] is None
    assert not summarize(tasks, [0, 1, 2])["valid"]


@pytest.mark.parametrize(
    "phases, expected",
    [
        ({"setup": "passed", "call": "passed", "teardown": "passed"}, "passed"),
        ({"setup": "passed", "call": "failed", "teardown": "passed"}, "failed"),
        ({"setup": "passed", "call": "failed", "teardown": "error"}, "error"),
        ({"setup": "skipped", "teardown": "passed"}, "skipped"),
        ({"setup": "passed"}, "error"),
    ],
)
def test_fixture_and_teardown_evidence_cannot_be_ignored(phases, expected):
    assert (
        plugin.status_for_phases({phase: {"status": status} for phase, status in phases.items()})
        == expected
    )


def test_every_curated_fault_is_a_distinct_valid_sql_mutation():
    catalog = json.loads((ROOT / "faults.json").read_text())
    ids = []
    for task, faults in catalog.items():
        mutations = MutationSet(
            tuple(
                Mutant("function", fault["target"], (Replace(fault["old"], fault["new"]),))
                for fault in faults
            )
        )
        prepared = prepare_mutants(mutations, (ROOT / "tasks" / task / "schema.sql").read_text())
        ids.extend(mutant.mutant_id for mutant in prepared)
        assert all(fault["trigger"] for fault in faults)
    assert len(ids) == len(set(ids)) == 12


def test_pytest_evidence_distinguishes_assertions_from_errors_and_skips(pytester, monkeypatch):
    output = pytester.path / "result.json"
    monkeypatch.setenv("PYTHONPATH", str(ROOT.parent.parent))
    monkeypatch.setenv("SQLPROOF_BENCHMARK_EXAMPLES", "5")
    monkeypatch.setenv("SQLPROOF_BENCHMARK_RESULT", str(output))
    pytester.makepyfile("""
        import pytest

        def test_passes():
            assert 1 == 1

        def test_assertion():
            assert False

        def test_runtime_error():
            raise RuntimeError("not evidence of a semantic fault")

        @pytest.fixture
        def broken():
            raise AssertionError("fixture assertions are infrastructure errors")

        def test_fixture_error(broken):
            pass

        @pytest.fixture
        def broken_teardown():
            yield
            raise RuntimeError("teardown failed")

        def test_teardown_error(broken_teardown):
            assert False

        @pytest.mark.skip(reason="no credit")
        def test_skipped():
            pass
    """)
    pytester.runpytest_subprocess("-p", "benchmarks.sql.plugin", "-q", "-o", "addopts=")
    tests = json.loads(output.read_text())["tests"]
    statuses = {name.split("::")[-1]: test["status"] for name, test in tests.items()}
    assert statuses == {
        "test_passes": "passed",
        "test_assertion": "failed",
        "test_runtime_error": "error",
        "test_fixture_error": "error",
        "test_teardown_error": "error",
        "test_skipped": "skipped",
    }


@pytest.mark.parametrize("decorator", ["@settings(max_examples=6)", "@seed(999)"])
def test_properties_cannot_override_the_shared_budget_or_seed(pytester, monkeypatch, decorator):
    output = pytester.path / "result.json"
    monkeypatch.setenv("PYTHONPATH", str(ROOT.parent.parent))
    monkeypatch.setenv("SQLPROOF_BENCHMARK_EXAMPLES", "5")
    monkeypatch.setenv("SQLPROOF_BENCHMARK_RESULT", str(output))
    pytester.makepyfile(f"""
        from hypothesis import given, seed, settings, strategies as st

        {decorator}
        @given(st.integers())
        def test_property(n):
            assert n == n
    """)
    result = pytester.runpytest_subprocess("-p", "benchmarks.sql.plugin", "-q", "-o", "addopts=")
    assert result.ret != 0
    assert score(json.loads(output.read_text()), {})["status"] == "error"
