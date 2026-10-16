"""Both directions of RLS access, plus anonymous requests with no subject."""

from hypothesis import given
from hypothesis import strategies as st

from sqlproof.contrib.supabase import as_rls_user


@given(data=st.data())
def test_an_owner_can_read_their_own_notes(supabase_proof, data):
    """Oracle: the owner ID in a generated row, with the authenticated role enforced."""
    dataset = data.draw(supabase_proof.dataset_strategy(sizes={"notes": 1, "auth.users": 2}))
    note = dataset["notes"][0]
    with supabase_proof.client_for_dataset(dataset) as db:
        with as_rls_user(db, note["owner_id"]):
            assert db.scalar("SELECT current_user") == "authenticated"
            rows = db.query("SELECT id FROM notes")
        assert rows == [{"id": note["id"]}]


@given(data=st.data())
def test_other_users_cannot_read_notes_they_do_not_own(supabase_proof, data):
    """Oracle: a distinct pool user is not the generated note's owner."""
    dataset = data.draw(supabase_proof.dataset_strategy(sizes={"notes": 1, "auth.users": 2}))
    note = dataset["notes"][0]
    outsider = next(user["id"] for user in dataset["auth.users"] if user["id"] != note["owner_id"])
    with supabase_proof.client_for_dataset(dataset) as db:
        with as_rls_user(db, outsider):
            assert db.scalar("SELECT current_user") == "authenticated"
            rows = db.query("SELECT id FROM notes")
        assert rows == []


@given(data=st.data())
def test_anonymous_requests_cannot_read_any_notes(supabase_proof, data):
    """Oracle: no subject grants access to no rows, regardless of the generated owner."""
    dataset = data.draw(supabase_proof.dataset_strategy(sizes={"notes": 1}))
    with supabase_proof.client_for_dataset(dataset) as db:
        with as_rls_user(
            db, dataset["notes"][0]["owner_id"], role="anon", extra_claims={"sub": None}
        ):
            assert db.scalar("SELECT current_user") == "anon"
            assert db.scalar("SELECT auth.uid()") is None
            rows = db.query("SELECT id FROM notes")
        assert rows == []
