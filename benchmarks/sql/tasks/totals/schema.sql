CREATE TABLE accounts (id bigint PRIMARY KEY);
CREATE TABLE payments (
    id bigint PRIMARY KEY,
    account_id bigint NOT NULL REFERENCES accounts(id),
    amount numeric(8, 2) NOT NULL CHECK (amount >= 0),
    status text NOT NULL CHECK (status IN ('paid', 'pending', 'void'))
);
CREATE FUNCTION paid_total(p_account bigint) RETURNS numeric LANGUAGE sql STABLE AS $$
    SELECT COALESCE(SUM(amount), 0) FROM payments
    WHERE account_id = p_account AND status = 'paid'
$$;
