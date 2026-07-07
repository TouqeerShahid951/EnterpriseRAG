from rag.shared.evaluation.answer_checks import evaluate_literal_checks


def passes(answer: str, expected: str) -> bool:
    return evaluate_literal_checks(answer, [expected], []).passed


def test_literal_checks_accept_rounded_money_values() -> None:
    assert passes("Amazon reported $79.975 billion in AWS revenue.", "80")
    assert passes("Operating income was $68.593 billion.", "69")


def test_literal_checks_accept_pound_kilogram_equivalent() -> None:
    assert passes("Apollo returned about 47 pounds of lunar material.", "22 kilograms")


def test_literal_checks_accept_abstention_for_not_provided() -> None:
    assert passes("The indexed sources do not contain enough information.", "not provided")


def test_literal_checks_do_not_hide_decimal_or_year_errors() -> None:
    assert not passes("The growth forecast is 26 percent.", "2.6")
    assert not passes("The policy changed in 2024.", "2025")
