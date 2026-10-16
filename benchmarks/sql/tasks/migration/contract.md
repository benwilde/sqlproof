# Account-report migration

`account_report()` replaces a slower account-by-account report. It returns one
row for every account, including accounts without charges. Each row holds the
account ID, exact sum of its charge amounts, and number of its charges. Equal
amounts count separately. Accounts without charges have total zero and count zero.
With no accounts, it returns no rows. Row ordering is unspecified.

The previous query is an independent migration oracle:

```sql
SELECT a.id AS account_id,
       (SELECT COALESCE(SUM(c.amount), 0) FROM charges c WHERE c.account_id = a.id) AS total,
       (SELECT COUNT(*) FROM charges c WHERE c.account_id = a.id) AS entries
FROM accounts a
```
