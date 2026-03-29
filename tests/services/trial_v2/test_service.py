from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _progress(**kwargs):
    base = {
        "trend_slots_used": 0,
        "rerolls_used": 0,
        "takes_used": 0,
        "reward_earned_total": 0,
        "reward_claimed_total": 0,
        "reward_available": 0,
        "reward_reserved": 0,
        "updated_at": None,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_register_take_started_new_slot():
    from app.services.trial_v2.service import TrialV2Service

    db = MagicMock()
    svc = TrialV2Service(db)
    progress = _progress()

    with patch.object(svc, "get_or_create_progress", return_value=progress):
        with patch.object(svc, "_get_slot", return_value=None):
            ok, err, used_reroll = svc.register_take_started(
                user_id="u1",
                trend_id="t1",
                take_id="take-1",
            )

    assert ok is True
    assert err is None
    assert used_reroll is False
    assert progress.trend_slots_used == 1
    assert progress.takes_used == 1


def test_register_take_started_reroll_path():
    from app.services.trial_v2.service import TrialV2Service

    db = MagicMock()
    svc = TrialV2Service(db)
    progress = _progress(trend_slots_used=1, rerolls_used=0, takes_used=1)
    slot = SimpleNamespace(takes_count=1, reroll_used=False, last_take_id="old")

    with patch.object(svc, "get_or_create_progress", return_value=progress):
        with patch.object(svc, "_get_slot", return_value=slot):
            ok, err, used_reroll = svc.register_take_started(
                user_id="u1",
                trend_id="t1",
                take_id="take-2",
            )

    assert ok is True
    assert err is None
    assert used_reroll is True
    assert slot.takes_count == 2
    assert slot.reroll_used is True
    assert progress.rerolls_used == 1
    assert progress.takes_used == 2


def test_award_referral_reward_cap_reached():
    from app.services.trial_v2.service import TrialV2Service

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    svc = TrialV2Service(db)
    progress = _progress(reward_earned_total=10, reward_available=1)

    with patch.object(svc, "get_or_create_progress", return_value=progress):
        created, available = svc.award_referral_reward(
            referrer_user_id="ref-1",
            referral_user_id="new-1",
        )

    assert created is False
    assert available == 1


def test_claim_next_reward_selection_no_selection_keeps_reward_reserved():
    from app.services.trial_v2.service import TrialV2Service

    db = MagicMock()
    svc = TrialV2Service(db)
    progress = _progress(reward_available=2, reward_reserved=0)

    with patch.object(svc, "get_or_create_progress", return_value=progress):
        with patch.object(svc, "get_oldest_pending_selection", return_value=None):
            status, selection = svc.claim_next_reward_selection("u1")

    assert status == "no_selection"
    assert selection is None
    assert progress.reward_reserved == 2


def test_process_first_successful_preview_creates_push_payload():
    from app.services.trial_v2.service import TrialV2Service

    db = MagicMock()
    svc = TrialV2Service(db)

    referral_user = SimpleNamespace(
        id="new-1",
        referred_by_user_id="ref-1",
        trial_first_preview_completed=False,
        trial_first_preview_completed_at=None,
    )
    referrer = SimpleNamespace(id="ref-1", telegram_id="100500")

    q1 = MagicMock()
    q1.filter.return_value.with_for_update.return_value.one_or_none.return_value = referral_user
    q2 = MagicMock()
    q2.filter.return_value.one_or_none.return_value = referrer
    db.query.side_effect = [q1, q2]

    with patch.object(svc, "award_referral_reward", return_value=(True, 3)):
        payload = svc.process_first_successful_preview("new-1")

    assert payload is not None
    assert payload["referrer_telegram_id"] == "100500"
    assert payload["reward_available"] == 3
    assert referral_user.trial_first_preview_completed is True

