import pytest

from app.core.status_machine import next_status


@pytest.mark.parametrize(
    "current, author, note, expected",
    [
        ("New", "contact", False, "On You"),
        ("On You", "contact", False, "On You"),
        ("On Customer", "contact", False, "On You"),
        ("Closed", "contact", False, "On You"),  # reopen
        ("New", "user", False, "On Customer"),
        ("On You", "user", False, "On Customer"),
        ("Closed", "user", False, "Closed"),  # a team reply never reopens
        ("On Hold", "contact", False, "On Hold"),  # On Hold is never auto-changed
        ("On Hold", "user", False, "On Hold"),
        ("On You", "user", True, "On You"),  # internal notes never transition
        ("Closed", "contact", True, "Closed"),
    ],
)
def test_next_status(current, author, note, expected):
    assert next_status(current, author_type=author, is_internal_note=note) == expected
