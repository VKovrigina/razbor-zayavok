from classify.rule_based import classify_rule_based
from db.models import ReplyCategory


def test_negative_marker_detected():
    assert classify_rule_based("Неактуально, спасибо") == ReplyCategory.NEGATIVE
    assert classify_rule_based("позовите оператора пожалуйста") == ReplyCategory.NEGATIVE


def test_question_is_ambiguous():
    assert classify_rule_based("Все верно, интересует стоимость") == ReplyCategory.AMBIGUOUS
    assert classify_rule_based("А сколько это будет стоить?") == ReplyCategory.AMBIGUOUS


def test_clear_agreement_is_positive():
    assert classify_rule_based("Да, все верно") == ReplyCategory.POSITIVE
    assert classify_rule_based("Хорошо, согласен") == ReplyCategory.POSITIVE


def test_unclear_reply_defaults_to_ambiguous():
    assert classify_rule_based("хм ладно посмотрим") == ReplyCategory.AMBIGUOUS
