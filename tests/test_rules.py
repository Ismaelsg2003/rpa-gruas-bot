import pytest

from bot.models import Operator, Rule, Service
from bot.rules import RuleError, decide, evaluate_rule
from tests.conftest import make_service


def rule(field: str, op: Operator, value: str, active: bool = True, name: str = "r") -> Rule:
    return Rule(id=1, name=name, field=field, operator=op, value=value, active=active)


@pytest.mark.parametrize(
    ("field", "op", "value", "expected"),
    [
        ("amount_eur", Operator.GTE, "90", True),
        ("amount_eur", Operator.GT, "90", False),
        ("distance_km", Operator.LTE, "12,5", True),  # comma decimal accepted
        ("distance_km", Operator.LT, "10", False),
        ("zone", Operator.IN, "Centro, Norte", True),
        ("zone", Operator.IN, "Sur,Este", False),
        ("zone", Operator.NOT_IN, "Sur,Este", True),
        ("service_type", Operator.EQ, "arrastre", True),  # case-insensitive
        ("service_type", Operator.NE, "Apertura", True),
        ("insurer", Operator.IN, "Aseguradora Alfa,Seguros Beta", True),
        ("amount_eur", Operator.EQ, "90.00", True),
    ],
)
def test_evaluate_rule(service: Service, field: str, op: Operator, value: str, expected: bool) -> None:
    assert evaluate_rule(service, rule(field, op, value)) is expected


def test_decide_accepts_when_all_rules_pass(service: Service) -> None:
    rules = [rule("zone", Operator.IN, "Centro"), rule("amount_eur", Operator.GTE, "50")]
    assert decide(service, rules).accepted


def test_decide_reports_first_failing_rule() -> None:
    cheap = make_service(amount_eur=40.0)
    rules = [rule("zone", Operator.IN, "Centro", name="Zona"), rule("amount_eur", Operator.GTE, "55", name="Importe mínimo")]
    decision = decide(cheap, rules)
    assert not decision.accepted
    assert decision.reason == "No cumple: Importe mínimo"


def test_inactive_rules_are_ignored(service: Service) -> None:
    rules = [rule("amount_eur", Operator.GTE, "999", active=False)]
    assert decide(service, rules).accepted


def test_no_rules_accepts_everything(service: Service) -> None:
    assert decide(service, []).accepted


@pytest.mark.parametrize(
    ("field", "op", "value"),
    [
        ("customer", Operator.EQ, "x"),  # unknown field
        ("amount_eur", Operator.GTE, "barato"),  # not a number
        ("zone", Operator.GTE, "5"),  # numeric operator on a text field
        ("zone", Operator.IN, "  "),  # empty value
    ],
)
def test_invalid_rules_raise(service: Service, field: str, op: Operator, value: str) -> None:
    with pytest.raises(RuleError):
        evaluate_rule(service, rule(field, op, value))
