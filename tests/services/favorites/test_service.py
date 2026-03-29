from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.favorites.service import FavoriteService


def test_remove_favorite_for_user_returns_false_when_not_found():
    db = MagicMock()
    db.query.return_value.filter.return_value.one_or_none.return_value = None
    svc = FavoriteService(db)

    assert svc.remove_favorite_for_user("user-1", "fav-1") is False
    db.delete.assert_not_called()
    db.flush.assert_not_called()


def test_remove_favorite_for_user_returns_false_for_delivered():
    db = MagicMock()
    fav = SimpleNamespace(hd_status="delivered")
    db.query.return_value.filter.return_value.one_or_none.return_value = fav
    svc = FavoriteService(db)

    assert svc.remove_favorite_for_user("user-1", "fav-1") is False
    db.delete.assert_not_called()
    db.flush.assert_not_called()


def test_remove_favorite_for_user_deletes_pending_favorite():
    db = MagicMock()
    fav = SimpleNamespace(hd_status="none")
    db.query.return_value.filter.return_value.one_or_none.return_value = fav
    svc = FavoriteService(db)

    assert svc.remove_favorite_for_user("user-1", "fav-1") is True
    db.delete.assert_called_once_with(fav)
    db.flush.assert_called_once()

