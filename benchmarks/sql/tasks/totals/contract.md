# Paid totals

`paid_total(account_id)` returns the exact sum of every paid payment belonging
to that account. Pending and void payments, and payments for other accounts,
contribute nothing. Equal payment amounts are separate payments and each counts.
An account with no paid payments, including an unknown account, returns zero.

Amounts are nonnegative decimals with two fractional places. The schema defines
the remaining input constraints. Queries must not change the stored payments.
