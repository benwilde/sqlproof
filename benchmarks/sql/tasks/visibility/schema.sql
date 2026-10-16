CREATE TABLE notes (
    id bigint PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES auth.users(id),
    body text NOT NULL
);
CREATE FUNCTION can_read_note(p_owner uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT p_owner = auth.uid()
$$;
ALTER TABLE notes ENABLE ROW LEVEL SECURITY;
CREATE POLICY read_own_notes ON notes FOR SELECT USING (can_read_note(owner_id));
GRANT SELECT ON notes TO authenticated, anon;
