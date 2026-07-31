import pytest

from cases.models import CaseStatus


def test_task_exists_false_when_absent(cases_repo):
    assert cases_repo.task_exists(1) is False


def test_insert_posted_creates_row_with_status_posted(cases_repo):
    assert cases_repo.insert_posted(1, 100) is True
    case = cases_repo.get_case(1)
    assert case is not None
    assert case.deal_id == 100
    assert case.status == CaseStatus.POSTED


def test_task_exists_true_after_insert(cases_repo):
    cases_repo.insert_posted(1, 100)
    assert cases_repo.task_exists(1) is True


def test_insert_posted_returns_false_on_duplicate_task_id(cases_repo):
    assert cases_repo.insert_posted(1, 100) is True
    assert cases_repo.insert_posted(1, 200) is False
    # исходная строка не перезаписана дублем
    case = cases_repo.get_case(1)
    assert case.deal_id == 100


@pytest.mark.parametrize(
    "status",
    [
        CaseStatus.POSTED,
        CaseStatus.CLAIMED,
        CaseStatus.FAILED_PUBLISH,
        CaseStatus.FAILED_CRM_UPDATE,
        CaseStatus.FAILED_GROUP_CREATION,
        CaseStatus.FAILED_CONTACT_SEND,
        CaseStatus.FAILED_CHANNEL_UNKNOWN,
    ],
)
def test_get_active_case_for_deal_returns_row_for_each_active_status(cases_repo, status):
    cases_repo.insert_posted(1, 100)
    cases_repo.set_status(1, status)
    active = cases_repo.get_active_case_for_deal(100)
    assert active is not None
    assert active.task_id == 1


@pytest.mark.parametrize(
    "status",
    [CaseStatus.GROUP_CREATED, CaseStatus.CONTACT_SENT, CaseStatus.RESOLVED_MANUALLY],
)
def test_get_active_case_for_deal_ignores_terminal_statuses(cases_repo, status):
    cases_repo.insert_posted(1, 100)
    cases_repo.set_status(1, status)
    assert cases_repo.get_active_case_for_deal(100) is None


def test_get_active_case_for_deal_none_when_no_rows(cases_repo):
    assert cases_repo.get_active_case_for_deal(999) is None


def test_claim_case_succeeds_when_status_posted(cases_repo):
    cases_repo.insert_posted(1, 100)
    assert cases_repo.claim_case(1, 555, "partner_nick") is True
    case = cases_repo.get_case(1)
    assert case.status == CaseStatus.CLAIMED
    assert case.claimed_by_tg_user_id == 555
    assert case.claimed_by_tg_username == "partner_nick"


def test_claim_case_fails_when_already_claimed(cases_repo):
    cases_repo.insert_posted(1, 100)
    assert cases_repo.claim_case(1, 555, "first") is True
    assert cases_repo.claim_case(1, 777, "second") is False
    case = cases_repo.get_case(1)
    assert case.claimed_by_tg_user_id == 555


def test_claim_case_fails_when_task_id_unknown(cases_repo):
    assert cases_repo.claim_case(999, 555, "nick") is False


def test_set_status_transitions_to_terminal_value(cases_repo):
    cases_repo.insert_posted(1, 100)
    cases_repo.set_status(1, CaseStatus.GROUP_CREATED)
    assert cases_repo.get_case(1).status == CaseStatus.GROUP_CREATED


def test_kv_set_then_get_roundtrip(cases_repo):
    cases_repo.set_kv("alerted:1", "1")
    assert cases_repo.get_kv("alerted:1") == "1"


def test_kv_get_returns_none_when_absent(cases_repo):
    assert cases_repo.get_kv("missing") is None


def test_kv_set_overwrites_existing_key(cases_repo):
    cases_repo.set_kv("alerted:1", "1")
    cases_repo.set_kv("alerted:1", "0")
    assert cases_repo.get_kv("alerted:1") == "0"
