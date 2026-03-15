"""
Тесты admin audit: _admin_audit actor_id fallback, порядок delete → audit для packs и themes.
"""
from unittest.mock import MagicMock, patch

import pytest


class TestAdminAuditActorId:
    """_admin_audit подставляет actor_id 'unknown' при отсутствии username в current_user."""

    def test_actor_id_unknown_when_username_missing(self):
        from app.api.routes.admin import _admin_audit

        db = MagicMock()
        current_user = {}
        with patch("app.api.routes.admin.AuditService") as AuditSvc:
            _admin_audit(db, current_user, "update", "settings", None, {"section": "app"})
        AuditSvc.return_value.log.assert_called_once()
        call_kw = AuditSvc.return_value.log.call_args[1]
        assert call_kw["actor_id"] == "unknown"
        assert call_kw["actor_type"] == "admin"
        assert call_kw["action"] == "update"

    def test_actor_id_username_when_present(self):
        from app.api.routes.admin import _admin_audit

        db = MagicMock()
        current_user = {"username": "admin@test"}
        with patch("app.api.routes.admin.AuditService") as AuditSvc:
            _admin_audit(db, current_user, "update", "settings", None, {})
        call_kw = AuditSvc.return_value.log.call_args[1]
        assert call_kw["actor_id"] == "admin@test"


class TestPacksDeleteAuditOrder:
    """packs_delete: audit только после успешного удаления; при 404 audit не вызывается."""

    def test_audit_called_after_successful_delete(self):
        from app.api.routes.admin import packs_delete

        db = MagicMock()
        pack = MagicMock()
        pack.id = "pack-1"
        pack.name = "Test Pack"
        db.query.return_value.filter.return_value.first.return_value = pack
        current_user = {"username": "admin"}

        with patch("app.api.routes.admin._admin_audit") as mock_audit:
            result = packs_delete(
                pack_id="pack-1",
                db=db,
                current_user=current_user,
            )
        assert result == {"ok": True}
        db.delete.assert_called_once_with(pack)
        db.commit.assert_called_once()
        mock_audit.assert_called_once()
        mock_audit.assert_called_with(
            db,
            current_user,
            "delete",
            "pack",
            "pack-1",
            {"name": "Test Pack"},
        )

    def test_audit_not_called_when_pack_not_found(self):
        from app.api.routes.admin import packs_delete
        from fastapi import HTTPException

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        current_user = {"username": "admin"}

        with patch("app.api.routes.admin._admin_audit") as mock_audit:
            with pytest.raises(HTTPException) as exc_info:
                packs_delete(pack_id="nonexistent", db=db, current_user=current_user)
        assert exc_info.value.status_code == 404
        mock_audit.assert_not_called()

    def test_audit_not_called_when_commit_fails(self):
        from app.api.routes.admin import packs_delete

        db = MagicMock()
        pack = MagicMock()
        pack.id = "pack-1"
        pack.name = "Test Pack"
        db.query.return_value.filter.return_value.first.return_value = pack
        db.commit.side_effect = Exception("FK constraint")

        with patch("app.api.routes.admin._admin_audit") as mock_audit:
            with pytest.raises(Exception):
                packs_delete(
                    pack_id="pack-1",
                    db=db,
                    current_user={"username": "admin"},
                )
        mock_audit.assert_not_called()


class TestThemesDeleteAuditOrder:
    """admin_themes_delete: audit только после успешного удаления; при 404 audit не вызывается."""

    def test_audit_called_after_successful_delete(self):
        from app.api.routes.admin import admin_themes_delete

        db = MagicMock()
        theme = MagicMock()
        theme.id = "theme-1"
        theme.name = "Test Theme"
        svc = MagicMock()
        svc.get.return_value = theme
        current_user = {"username": "admin"}

        with (
            patch("app.api.routes.admin.ThemeService", return_value=svc),
            patch("app.api.routes.admin._admin_audit") as mock_audit,
        ):
            result = admin_themes_delete(
                theme_id="theme-1",
                db=db,
                current_user=current_user,
            )
        assert result == {"ok": True}
        svc.delete.assert_called_once_with(theme)
        mock_audit.assert_called_once()
        mock_audit.assert_called_with(
            db,
            current_user,
            "delete",
            "theme",
            "theme-1",
            {"name": "Test Theme"},
        )

    def test_audit_not_called_when_theme_not_found(self):
        from app.api.routes.admin import admin_themes_delete
        from fastapi import HTTPException

        svc = MagicMock()
        svc.get.return_value = None

        with (
            patch("app.api.routes.admin.ThemeService", return_value=svc),
            patch("app.api.routes.admin._admin_audit") as mock_audit,
        ):
            with pytest.raises(HTTPException) as exc_info:
                admin_themes_delete(
                    theme_id="nonexistent",
                    db=MagicMock(),
                    current_user={"username": "admin"},
                )
        assert exc_info.value.status_code == 404
        mock_audit.assert_not_called()
