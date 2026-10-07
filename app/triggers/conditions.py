from typing import Any

from app.models import TriggerCondition

# Field paths are dotted: "<context_key>.<attribute>", e.g. "issue.title", "message.body_html".
_OPERATORS = {
    "equals": lambda actual, expected: actual == expected,
    "not_equals": lambda actual, expected: actual != expected,
    "contains": lambda actual, expected: expected in actual,
    "not_contains": lambda actual, expected: expected not in actual,
}


def _resolve_field(context: dict[str, Any], field: str) -> Any:
    context_key, _, attr = field.partition(".")
    obj = context.get(context_key)
    if obj is None or not attr:
        return None
    return getattr(obj, attr, None)


def _matches_condition(condition: TriggerCondition, context: dict[str, Any]) -> bool:
    comparator = _OPERATORS.get(condition.operator)
    if comparator is None:
        raise ValueError(f"unknown condition operator: {condition.operator}")
    actual = _resolve_field(context, condition.field)
    actual_str = "" if actual is None else str(actual)
    return comparator(actual_str, condition.value)


def evaluate(conditions: list[TriggerCondition], context: dict[str, Any]) -> bool:
    """AND all conditions together. A trigger with no conditions always matches."""
    return all(_matches_condition(condition, context) for condition in conditions)
