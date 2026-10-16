-- A fixed auth pool keeps UUIDs identical across seeds and database clones.
-- The server supplies the non-superuser authenticated and anon roles.
CREATE SCHEMA auth;
CREATE TABLE auth.users (id uuid PRIMARY KEY, email text NOT NULL UNIQUE);
INSERT INTO auth.users (id, email)
SELECT md5('sqlproof-benchmark-user-' || i)::uuid, 'sqlproof_' || i || '@test.invalid'
FROM generate_series(0, 4) AS users(i);

CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS $$
    SELECT (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub')::uuid
$$;
GRANT USAGE ON SCHEMA public, auth TO authenticated, anon;
GRANT EXECUTE ON FUNCTION auth.uid() TO authenticated, anon;
