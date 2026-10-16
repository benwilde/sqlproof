"""Checkout properties follow the documented credit, shipping and rounding rules."""

from decimal import ROUND_HALF_UP, Decimal

from hypothesis import example, given
from hypothesis import strategies as st


@given(subtotal=st.decimals(0, 10000, places=3), credit=st.decimals(0, 10000, places=3))
@example(subtotal=Decimal("100"), credit=Decimal("0"))
@example(subtotal=Decimal("10.005"), credit=Decimal("0"))
def test_checkout_total_matches_the_currency_contract(proof, subtotal, credit):
    """Oracle: Decimal arithmetic with explicit shipping and ROUND_HALF_UP cents."""
    merchandise = max(subtotal - credit, Decimal(0))
    shipping = Decimal(5) if subtotal < 100 else Decimal(0)
    expected = (merchandise + shipping).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    with proof.client_for_dataset({}) as db:
        total = db.scalar("SELECT checkout_total(%s::numeric, %s::numeric)", subtotal, credit)
    assert isinstance(total, Decimal)
    assert total == expected


@given(subtotal=st.decimals(0, 9000, places=3), excess=st.decimals(0, 1000, places=3))
def test_excess_credit_leaves_only_shipping_to_pay(proof, subtotal, excess):
    """Oracle: credit covering merchandise leaves exactly the documented shipping fee."""
    with proof.client_for_dataset({}) as db:
        total = db.scalar(
            "SELECT checkout_total(%s::numeric, %s::numeric)", subtotal, subtotal + excess
        )
    assert total == (Decimal(5) if subtotal < 100 else Decimal(0))
