"""
Unit-тесты для prepare_delivery с моком PreviewService (без реального PIL/файлов изображений).
"""
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.paywall.delivery import prepare_delivery
from app.paywall.models import AccessDecision, UnlockOptions


def _fake_db():
    return MagicMock()


class TestPrepareDelivery(unittest.TestCase):
    @patch("app.paywall.delivery.PreviewService")
    def test_show_preview_copies_and_builds_preview(self, mock_preview_svc):
        def fake_build_preview(original_path: str, preview_path: str, scenario: str, *, db) -> str:
            base, _ = os.path.splitext(preview_path)
            out = base + ".webp"
            os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
            with open(out, "wb") as f:
                f.write(b"preview")
            return out

        mock_preview_svc.build_preview.side_effect = fake_build_preview
        decision = AccessDecision(
            show_preview=True,
            unlock_options=UnlockOptions(show_tokens=True, show_stars=True, cost_tokens=1, cost_stars=2),
        )
        with tempfile.TemporaryDirectory() as tmp:
            raw = os.path.join(tmp, "raw.png")
            with open(raw, "wb") as f:
                f.write(b"x")
            out_dir = os.path.join(tmp, "outputs")
            result = prepare_delivery(decision, raw, out_dir, job_id="job1", attempt=1, db=_fake_db())
        self.assertTrue(result.is_preview)
        self.assertIsNotNone(result.preview_path)
        self.assertIn("job1_1_preview", result.preview_path)
        self.assertIn("job1_1_original", result.original_path)
        self.assertTrue(os.path.isfile(result.original_path))
        self.assertTrue(os.path.isfile(result.preview_path))
        mock_preview_svc.build_preview.assert_called_once()

    def test_no_preview_returns_raw_as_original(self):
        decision = AccessDecision(
            show_preview=False,
            unlock_options=UnlockOptions(show_tokens=True, show_stars=True, cost_tokens=1, cost_stars=2),
        )
        with tempfile.TemporaryDirectory() as tmp:
            raw = os.path.join(tmp, "raw.png")
            with open(raw, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n")
            out_dir = os.path.join(tmp, "out")
            result = prepare_delivery(decision, raw, out_dir, job_id="job1", attempt=1, db=_fake_db())
        self.assertFalse(result.is_preview)
        self.assertIsNone(result.preview_path)
        self.assertEqual(result.original_path, raw)

    def test_missing_raw_raises(self):
        decision = AccessDecision(
            show_preview=False,
            unlock_options=UnlockOptions(show_tokens=True, show_stars=True, cost_tokens=1, cost_stars=2),
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                prepare_delivery(decision, os.path.join(tmp, "nonexistent.png"), tmp, "j", 1, db=_fake_db())
