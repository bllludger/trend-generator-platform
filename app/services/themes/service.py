from sqlalchemy.orm import Session

from app.models.theme import Theme


class ThemeService:
    def __init__(self, db: Session):
        self.db = db

    def list_all(self) -> list[Theme]:
        return self.db.query(Theme).order_by(Theme.order_index.asc()).all()

    def get(self, theme_id: str) -> Theme | None:
        return self.db.query(Theme).filter(Theme.id == theme_id).one_or_none()

    def create(self, data: dict) -> Theme:
        theme = Theme(**data)
        self.db.add(theme)
        self.db.commit()
        self.db.refresh(theme)
        return theme

    def update(self, theme: Theme, data: dict) -> Theme:
        for key, value in data.items():
            setattr(theme, key, value)
        self.db.add(theme)
        self.db.commit()
        self.db.refresh(theme)
        return theme

    def delete(self, theme: Theme) -> None:
        self.db.delete(theme)
        self.db.commit()

    def patch_order(self, theme_id: str, direction: str) -> Theme | None:
        theme = self.get(theme_id)
        if not theme:
            return None
        themes = self.list_all()
        idx = next((i for i, t in enumerate(themes) if t.id == theme_id), None)
        if idx is None:
            return None
        if direction == "up" and idx == 0:
            return theme
        if direction == "down" and idx >= len(themes) - 1:
            return theme
        swap_idx = idx - 1 if direction == "up" else idx + 1
        other = themes[swap_idx]
        self.update(theme, {"order_index": other.order_index})
        self.update(other, {"order_index": theme.order_index})
        self.db.refresh(theme)
        return theme
