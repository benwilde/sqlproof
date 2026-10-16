CREATE TABLE accounts (id bigint PRIMARY KEY);
CREATE TABLE charges (
    id bigint PRIMARY KEY,
    account_id bigint NOT NULL REFERENCES accounts(id),
    amount numeric(8, 2) NOT NULL CHECK (amount >= 0)
);
CREATE FUNCTION account_report() RETURNS TABLE (account_id bigint, total numeric, entries bigint)
LANGUAGE sql STABLE AS $$
    SELECT a.id, COALESCE(SUM(c.amount), 0), COUNT(c.id)
    FROM accounts AS a LEFT JOIN charges AS c ON c.account_id = a.id
    GROUP BY a.id
$$;
