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


def test_bare_da_is_positive():
    """P-013: голое "Да" без запятой/точки/восклицания тоже должно матчиться как позитив, но
    без ложных срабатываний на словах, содержащих "да" как часть слова."""
    assert classify_rule_based("Да") == ReplyCategory.POSITIVE
    assert classify_rule_based("да") == ReplyCategory.POSITIVE
    assert classify_rule_based("Иногда бывает по-разному") == ReplyCategory.AMBIGUOUS
    assert classify_rule_based("Куда там, не успеем") == ReplyCategory.AMBIGUOUS


def test_soft_deferral_treated_as_negative():
    """Мягкие отказы без "неактуально" — клиент откладывает без объяснения причины, это
    считается отказом (negative), а не неоднозначным ответом."""
    assert classify_rule_based("Пока нет") == ReplyCategory.NEGATIVE
    assert classify_rule_based("Не сейчас, может позже") == ReplyCategory.NEGATIVE
    assert classify_rule_based("Пока не готовы") == ReplyCategory.NEGATIVE
    assert classify_rule_based("Пока рано об этом говорить") == ReplyCategory.NEGATIVE
