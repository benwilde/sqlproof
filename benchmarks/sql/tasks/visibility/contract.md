# Note visibility

Authenticated users can read their own notes and cannot read other users' notes.
An anonymous request with no subject cannot read any note. These rules apply to
the actual rows returned by SELECT through the notes RLS policy.

`can_read_note(owner_id)` is the policy helper. Test through the policy with
`as_rls_user`, which sets both JWT claims and the database role. The admin
connection bypasses RLS. Use `supabase_proof` for generated auth-aware datasets.
For an anonymous request use role `anon` and `extra_claims={"sub": None}`.
