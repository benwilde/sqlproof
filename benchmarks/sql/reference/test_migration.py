"""A report migration preserves account coverage, totals and multiplicity."""

from hypothesis import given
from hypothesis import strategies as st

LEGACY = """
SELECT a.id AS account_id,
       (SELECT COALESCE(SUM(c.amount), 0) FROM charges c WHERE c.account_id = a.id) AS total,
       (SELECT COUNT(*) FROM charges c WHERE c.account_id = a.id) AS entries
FROM accounts a ORDER BY a.id
"""


@given(data=st.data())
def test_the_new_report_matches_the_previous_query(proof, data):
    """Oracle: the independently written correlated-subquery report in the contract."""
    accounts = data.draw(st.integers(0, 3))
    charges = data.draw(st.integers(0, 10)) if accounts else 0
    dataset = data.draw(
        proof.dataset_strategy(
            sizes={"accounts": accounts, "charges": charges},
            columns={"charges.amount": st.decimals(0, 100, places=2)},
        )
    )
    with proof.client_for_dataset(dataset) as db:
        assert db.query("SELECT * FROM account_report() ORDER BY account_id") == db.query(LEGACY)


@given(data=st.data(), amount=st.decimals("0.01", "100", places=2), count=st.integers(2, 6))
def test_equal_charge_amounts_are_counted_as_separate_charges(proof, data, amount, count):
    """Oracle: the number of generated charges times their shared nonzero amount."""
    dataset = data.draw(
        proof.dataset_strategy(
            sizes={"accounts": 1, "charges": count},
            columns={"charges.amount": amount},
        )
    )
    with proof.client_for_dataset(dataset) as db:
        assert db.query("SELECT * FROM account_report()") == [
            {
                "account_id": dataset["accounts"][0]["id"],
                "total": amount * count,
                "entries": count,
            }
        ]
