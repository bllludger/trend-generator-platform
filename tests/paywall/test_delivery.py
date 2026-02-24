"""
Unit-тесты для prepare_delivery с моком watermark (без реального PIL/файлов изображений).
"""
import os
import tempfile
import unittest
from unittest.mock import patch

from app.paywall.delivery import prepare_delivery
from app.paywall.models import AccessDecision, UnlockOptions


class TestPrepareDelivery(unittest.TestCase):
    @patch("app.paywall.delivery.apply_watermark")
    def test_show_preview_copies_and_watermarks(self, mock_watermark):
        def fake_watermark(src: str, dst: str) -> str:
            os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
            with open(dst, "wb") as f:
                f.write(b"preview")
            return dst

        mock_watermark.side_effect = fake_watermark
        decision = AccessDecision(
            show_preview=True,
            unlock_options=UnlockOptions(show_tokens=True, show_stars=True, cost_tokens=1, cost_stars=2),
        )
        with tempfile.TemporaryDirectory() as tmp:
            raw = os.path.join(tmp, "raw.png")
            with open(raw, "wb") as f:
                f.write(b"x")
            out_dir = os.path.join(tmp, "outputs")
            result = prepare_delivery(decision, raw, out_dir, job_id="job1", attempt=1)
        self.assertTrue(result.is_preview)
        self.assertIsNotNone(result.preview_path)
        self.assertIn("job1_1_preview", result.preview_path)
        self.assertIn("job1_1_original", result.original_path)
        self.assertTrue(os.path.isfile(result.original_path))
        self.assertTrue(os.path.isfile(result.preview_path))
        mock_watermark.assert_called_once()

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
            result = prepare_delivery(decision, raw, out_dir, job_id="job1", attempt=1)
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
                prepare_delivery(decision, os.path.join(tmp, "nonexistent.png"), tmp, "j", 1)
