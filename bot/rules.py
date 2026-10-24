"""Rule engine: decides whether a service fits the company's criteria.

A service is accepted only if it passes every active rule (logical AND).
Rule values are stored as text and parsed here:
- numeric operators (gt, gte, lt, lte) compare as floats ("12,5" is accepted)
- in / not_in take a comma-separated list, e.g. "Centro,Norte"
- eq / ne compare case-insensitively as text (or as numbers on numeric fields)
"""

from __future__ import annotations

from collections.abc import Iterable

from bot.models import NUMERIC_FIELDS, RULE_FIELDS, Decision, Operator, Rule, Service


class RuleError(ValueError):
    """Raised when a rule is malformed."""


def _split_list(raw: str) -> set[str]:
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _to_float(raw: object, rule: Rule) -> float:
    try:
        return float(str(raw).replace(",", "."))
    except ValueError as exc:
        raise RuleError(f"Regla '{rule.name}': '{raw}' no es un número") from exc


def validate_rule(rule: Rule) -> None:
    if rule.field not in RULE_FIELDS:
        raise RuleError(f"Regla '{rule.name}': campo desconocido '{rule.field}'")
    numeric_ops = {Operator.GT, Operator.GTE, Operator.LT, Operator.LTE}
    if rule.operator in numeric_ops and rule.field not in NUMERIC_FIELDS:
        raise RuleError(f"Regla '{rule.name}': '{rule.operator}' solo vale para campos numéricos")
    if rule.field in NUMERIC_FIELDS and rule.operator in numeric_ops | {Operator.EQ, Operator.NE}:
        _to_float(rule.value, rule)
    if not rule.value.strip():
        raise RuleError(f"Regla '{rule.name}': el valor está vacío")


def evaluate_rule(service: Service, rule: Rule) -> bool:
    validate_rule(rule)
    actual = getattr(service, rule.field)
    op = rule.operator

    if op in (Operator.GT, Operator.GTE, Operator.LT, Operator.LTE):
        a, b = float(actual), _to_float(rule.value, rule)
        return {Operator.GT: a > b, Operator.GTE: a >= b, Operator.LT: a < b, Operator.LTE: a <= b}[op]

    if op in (Operator.IN, Operator.NOT_IN):
        contained = str(actual).strip().lower() in _split_list(rule.value)
        return contained if op is Operator.IN else not contained

    if rule.field in NUMERIC_FIELDS:
        equal = float(actual) == _to_float(rule.value, rule)
    else:
        equal = str(actual).strip().lower() == rule.value.strip().lower()
    return equal if op is Operator.EQ else not equal


def decide(service: Service, rules: Iterable[Rule]) -> Decision:
    active = [r for r in rules if r.active]
    for rule in active:
        if not evaluate_rule(service, rule):
            return Decision(service.id, False, f"No cumple: {rule.name}")
    return Decision(service.id, True, "Cumple las reglas")
