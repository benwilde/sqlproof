# SQL property benchmark

This is a small test-effectiveness benchmark: four documented SQL tasks,
twelve curated semantic faults, and a reference suite of eight Hypothesis
properties plus one empty-state example. It measures which tests detect known
faults. The existing `tests/benchmarks/` benchmark measures generation speed.

| Task | Contract | Fault families |
| --- | --- | --- |
| Paid totals | [Account payment totals](tasks/totals/contract.md) | Account isolation, payment status, empty groups |
| Checkout | [Credit, shipping and rounding](tasks/pricing/contract.md) | Threshold boundary, excess credit, half-cent rounding |
| Visibility | [Note RLS](tasks/visibility/contract.md) | Cross-user access, owner denial, anonymous access |
| Migration | [Account report](tasks/migration/contract.md) | Missing empty accounts, duplicate amounts, phantom counts |

## Run the reference suite

Install the repository's existing development dependencies with
`uv sync --locked --extra dev`. From the repository root:

```sh
export SQLPROOF_BENCHMARK_DATABASE_URL='postgresql://postgres:postgres@127.0.0.1:5432/postgres'
uv run python -m benchmarks.sql
```

The supplied URL is a maintenance connection. The runner creates uniquely named
task templates from `template0` and uses SQLProof's existing mutation runner to
clone a fresh database for each correct/faulty execution. It drops its templates
and clones afterwards. It does not apply benchmark DDL to the supplied database.
The role needs `CREATEDB` and permission to `SET ROLE authenticated` and `anon`.
Both roles must already exist without superuser or `BYPASSRLS` privileges;
Supabase's PostgreSQL images provide them. Task databases have a minimal auth
schema and five fixed users, identical across clones.

Defaults are seeds **0, 1 and 42**, **40 generated examples per property**
(plus explicit examples), and a **120-second timeout per pytest subprocess**.
Hypothesis's example database is disabled. A full run performs 48 child pytest
runs: four tasks times three seeds times one correct version plus three faults.

```sh
# Replay a particular task/seed and choose a fresh report path.
uv run python -m benchmarks.sql --task visibility --seed 42 \
  --examples 40 --output .sqlproof/benchmarks/visibility-42.json
```

The JSON report records per-test outcomes for every fault and seed, baseline
evidence, exception types, versions, git state, content hashes, and elapsed
fault-run times. Test IDs map directly to readable pytest function names; each
baseline test is labelled `property` or `example`. For example:

```json
{
  "id": "owner_denied",
  "status": "caught",
  "properties": {
    "test_visibility.py::test_an_owner_can_read_their_own_notes": "failed",
    "test_visibility.py::test_other_users_cannot_read_notes_they_do_not_own": "passed",
    "test_visibility.py::test_anonymous_requests_cannot_read_any_notes": "passed"
  }
}
```

## Scoring

Each seed first runs the suite against correct SQL. Every collected test must
pass. The same tests then run with **one fault at a time** in fresh clones.
A test earns detection credit only for an assertion failure on faulty SQL and
a pass on correct SQL. Fixture/teardown failures, SQL/runtime exceptions,
timeouts, skips, xfails, missing tests and collection failures invalidate the
execution. This conservative rule keeps infrastructure failures out of recall.
Survivors remain in the denominator; errors produce an invalid score rather
than being dropped to inflate it.

The report distinguishes recall across all fault/seed evaluations from
`reliable_recall`: the fraction of faults caught on **every** requested seed.
The CLI exits 0 when all faults are detected, 1 for valid runs with survivors,
and 2 for invalid execution or setup. Existing report files are never overwritten.

## Evaluate another test suite

Put `test_totals.py`, `test_pricing.py`, `test_visibility.py` and
`test_migration.py` in a separate directory. Tests receive the normal SQLProof
pytest fixtures. Use `proof.dataset_strategy()` for business rows and
`supabase_proof`/`as_rls_user` for RLS. The reference suite shows the conventions.

```sh
uv run python -m benchmarks.sql --suite-dir /path/to/candidate-tests \
  --output .sqlproof/benchmarks/candidate.json
```

`--task` allows a partial submission. Tests must retain the runner's seed and
example budget; do not override them with `@seed`, `derandomize`, a private
example database or a different `max_examples`. Explicit edge examples are
allowed. Keep input tests unchanged between variants and runs.

For later model/prompt comparisons, give each agent only the task contracts,
schemas, fixture instructions and the same generation budget. Withhold
`faults.json` and `reference/` when generating a candidate suite. Freeze each
submission before scoring and retain its report. The harness currently scores
submitted tests; it does not invoke models or provide an isolated agent environment.

## Scope and provenance

The design takes the per-test fail-on-bug/pass-on-correct idea from
[PBT-Bench](https://arxiv.org/html/2605.15229v4) and applies it to PostgreSQL
through SQLProof's mutation runner. These are newly authored SQL tasks and
faults, not the paper's Python dataset or its full evaluation protocol.

The reference suite is a calibration check that all curated faults can be
detected within the budget. Its score is not evidence of general fault-finding
ability or a model ranking. Twelve public faults are too small a sample for
that claim, and can be overfit. No held-out evaluation, repeated model generations,
stateful tasks or direct policy mutations are included in this first version.
RLS faults affect the policy helper through the existing function-mutation API.

Run the harness checks with:

```sh
uv run pytest tests/unit/test_sql_benchmark.py
SQLPROOF_TEST_DATABASE_URL="$SQLPROOF_BENCHMARK_DATABASE_URL" \
  uv run pytest tests/integration/test_sql_benchmark_live.py
uv run ruff check benchmarks/
```
