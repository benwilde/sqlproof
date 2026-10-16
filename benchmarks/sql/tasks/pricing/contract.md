# Checkout totals

`checkout_total(subtotal, credit)` accepts nonnegative decimal amounts from zero
to 10,000, with up to three fractional places. Credit reduces the merchandise
charge but cannot make it negative. Shipping costs 5 when the original subtotal
is below 100, and zero at or above 100, regardless of credit.

The final total is rounded to two decimal places, with halfway cases rounded
away from zero. It is never negative. Inputs outside this domain are unspecified.
