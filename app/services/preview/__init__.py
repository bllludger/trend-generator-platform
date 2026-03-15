"""Единый сервис построения превью: resize → watermark → encode (Take и Job)."""
from app.services.preview.service import build_preview


class PreviewService:
    """Единая точка построения превью. Вызов: PreviewService.build_preview(...)."""
    build_preview = staticmethod(build_preview)


__all__ = ["PreviewService"]
