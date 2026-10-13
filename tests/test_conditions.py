from types import SimpleNamespace as NS

import pytest

from app.triggers import conditions


def cond(field, operator, value):
    return NS(field=field, operator=operator, value=value)


CTX = {"issue": NS(title="URGENT: prod down", status="New"), "message": None}


def test_no_conditions_always_matches():
    assert conditions.evaluate([], CTX) is True


@pytest.mark.parametrize(
    "field, operator, value, expected",
    [
        ("issue.title", "contains", "URGENT", True),
        ("issue.title", "contains", "urgent", False),  # case-sensitive
        ("issue.title", "not_contains", "refund", True),
        ("issue.status", "equals", "New", True),
        ("issue.status", "equals", "Closed", False),
        ("issue.status", "not_equals", "Closed", True),
    ],
)
def test_operators(field, operator, value, expected):
    assert conditions.evaluate([cond(field, operator, value)], CTX) is expected


def test_conditions_are_anded():
    both = [cond("issue.title", "contains", "URGENT"), cond("issue.status", "equals", "New")]
    one_false = [cond("issue.title", "contains", "URGENT"), cond("issue.status", "equals", "Closed")]
    assert conditions.evaluate(both, CTX) is True
    assert conditions.evaluate(one_false, CTX) is False


def test_missing_object_resolves_to_empty_string():
    assert conditions.evaluate([cond("message.body_html", "contains", "x")], CTX) is False


def test_unknown_operator_raises():
    with pytest.raises(ValueError):
        conditions.evaluate([cond("issue.title", "matches", "x")], CTX)
