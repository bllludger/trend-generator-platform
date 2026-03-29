from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def test_variants_for_take_collects_available_originals():
    from app.services.trial_bundle_order.service import TrialBundleOrderService

    db = MagicMock()
    svc = TrialBundleOrderService(db)
    take = SimpleNamespace(
        variant_a_original="/tmp/a.png",
        variant_b_original=None,
        variant_c_original="/tmp/c.png",
    )
    assert svc._variants_for_take(take) == ["A", "C"]


def test_create_or_get_order_reuses_pending_with_url():
    from app.services.trial_bundle_order.service import TrialBundleOrderService

    db = MagicMock()
    svc = TrialBundleOrderService(db)
    pending = SimpleNamespace(id="ord-1", confirmation_url="https://pay", status="payment_pending")

    with patch.object(svc, "get_pending_order", return_value=pending):
        order, url = svc.create_or_get_order(telegram_user_id="100", take_id="take-1")

    assert order == pending
    assert url == "https://pay"


def test_mark_paid_changes_status_from_pending():
    from app.services.trial_bundle_order.service import TrialBundleOrderService

    db = MagicMock()
    svc = TrialBundleOrderService(db)
    order = SimpleNamespace(status="payment_pending", updated_at=None)

    with patch.object(svc, "get_by_id", return_value=order):
        out = svc.mark_paid(order_id="ord-1")

    assert out is order
    assert order.status == "paid"


def test_mark_paid_ignores_terminal_status():
    from app.services.trial_bundle_order.service import TrialBundleOrderService

    db = MagicMock()
    svc = TrialBundleOrderService(db)
    order = SimpleNamespace(status="delivered", updated_at=None)

    with patch.object(svc, "get_by_id", return_value=order):
        out = svc.mark_paid(order_id="ord-1")

    assert out is None

