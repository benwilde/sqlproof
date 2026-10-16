"""Paid totals reconcile with independently selected Python payment amounts."""

from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st


@given(data=st.data())
def test_paid_total_matches_the_accounts_paid_payments(proof, data):
    """Oracle: Python sums only the generated account's paid payment rows."""
    dataset = data.draw(
        proof.dataset_strategy(
            sizes={"accounts": 3, "payments": st.integers(0, 10)},
            columns={"payments.amount": st.decimals(0, 100, places=2)},
        )
    )
    with proof.client_for_dataset(dataset) as db:
        for account in dataset["accounts"]:
            expected = sum(
                (
                    row["amount"]
                    for row in dataset["payments"]
                    if row["account_id"] == account["id"] and row["status"] == "paid"
                ),
                Decimal(0),
            )
            assert db.scalar("SELECT paid_total(%s::bigint)", account["id"]) == expected


def test_an_unknown_account_has_zero_paid_total(db):
    assert db.scalar("SELECT paid_total(%s::bigint)", 0) == Decimal(0)
