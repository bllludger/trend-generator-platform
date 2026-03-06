"""
Unit-тесты для PhotoMergeService.
Проверяем авто-макет 2/3 фото, размеры canvas, отсутствие апскейла.
"""
import os
import tempfile

import pytest
from PIL import Image, ExifTags

from app.services.photo_merge.service import PhotoMergeService


def _make_test_image(width: int, height: int, color=(255, 100, 100)) -> str:
    """Создать временное JPEG-изображение заданного размера, вернуть путь."""
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    img = Image.new("RGB", (width, height), color)
    img.save(tmp.name, "JPEG")
    tmp.close()
    return tmp.name


def _make_test_png(width: int, height: int, color=(100, 200, 100)) -> str:
    """Создать временное PNG-изображение, вернуть путь."""
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    img = Image.new("RGB", (width, height), color)
    img.save(tmp.name, "PNG")
    tmp.close()
    return tmp.name


@pytest.fixture
def svc() -> PhotoMergeService:
    return PhotoMergeService()


@pytest.fixture
def tmp_output_path():
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    path = tmp.name
    tmp.close()
    os.unlink(path)  # мы хотим чтобы путь был свободен
    yield path
    if os.path.exists(path):
        os.unlink(path)


class TestLayout2:
    def test_basic_merge_2_equal(self, svc, tmp_output_path):
        """2 равных фото склеиваются горизонтально, итоговая ширина = сумма."""
        p1 = _make_test_image(400, 300)
        p2 = _make_test_image(400, 300)
        try:
            metrics = svc.merge([p1, p2], tmp_output_path)
            result = Image.open(tmp_output_path)
            assert result.width == 800, f"ожидалась ширина 800, получено {result.width}"
            assert result.height == 300
            assert metrics["input_bytes"] > 0
            assert metrics["output_bytes"] > 0
        finally:
            os.unlink(p1)
            os.unlink(p2)

    def test_basic_merge_2_different_height(self, svc, tmp_output_path):
        """2 фото разной высоты: высокое уменьшается до размера меньшего."""
        p1 = _make_test_image(300, 200)  # меньшая высота
        p2 = _make_test_image(400, 600)  # большая высота
        try:
            svc.merge([p1, p2], tmp_output_path)
            result = Image.open(tmp_output_path)
            assert result.height == 200, f"ожидалась высота 200, получено {result.height}"
        finally:
            os.unlink(p1)
            os.unlink(p2)

    def test_no_upscale_2(self, svc, tmp_output_path):
        """Маленькое фото не апскейлится при совпадении высот."""
        p1 = _make_test_image(100, 100)
        p2 = _make_test_image(200, 100)
        try:
            svc.merge([p1, p2], tmp_output_path)
            result = Image.open(tmp_output_path)
            # Оба фото при target_h=100 остаются прежних размеров
            assert result.width == 300
            assert result.height == 100
        finally:
            os.unlink(p1)
            os.unlink(p2)

    def test_jpeg_output(self, svc):
        """Проверить корректный JPEG-вывод."""
        p1 = _make_test_image(200, 150)
        p2 = _make_test_image(200, 150)
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        out = tmp.name
        tmp.close()
        try:
            svc.merge([p1, p2], out, output_format="jpeg", jpeg_quality=80)
            result = Image.open(out)
            assert result.format == "JPEG"
        finally:
            os.unlink(p1)
            os.unlink(p2)
            os.unlink(out)

    def test_mix_formats(self, svc, tmp_output_path):
        """PNG + JPEG — должны склеиться без ошибок."""
        p1 = _make_test_image(200, 200)
        p2 = _make_test_png(300, 200)
        try:
            svc.merge([p1, p2], tmp_output_path)
            result = Image.open(tmp_output_path)
            assert result.width == 500
        finally:
            os.unlink(p1)
            os.unlink(p2)


class TestLayout3:
    def test_basic_merge_3(self, svc, tmp_output_path):
        """3 фото в сетке 2+1: итоговая ширина = сумма двух верхних."""
        p1 = _make_test_image(400, 300, (200, 50, 50))
        p2 = _make_test_image(400, 300, (50, 200, 50))
        p3 = _make_test_image(300, 200, (50, 50, 200))  # нижнее, уже верхних
        try:
            svc.merge([p1, p2, p3], tmp_output_path)
            result = Image.open(tmp_output_path)
            # Ширина = сумма двух верхних (оба 400) = 800
            assert result.width == 800
            # Высота = top_h + bot_h
            assert result.height > 300
        finally:
            os.unlink(p1)
            os.unlink(p2)
            os.unlink(p3)

    def test_merge_3_bottom_wider_clipped(self, svc, tmp_output_path):
        """Нижнее фото шире верхних — должно быть уменьшено до ширины верхних."""
        p1 = _make_test_image(200, 150)
        p2 = _make_test_image(200, 150)
        p3 = _make_test_image(800, 400)  # гораздо шире верхней пары
        try:
            svc.merge([p1, p2, p3], tmp_output_path)
            result = Image.open(tmp_output_path)
            # Ширина canvas = 400 (sum of top)
            assert result.width == 400
        finally:
            os.unlink(p1)
            os.unlink(p2)
            os.unlink(p3)

    def test_merge_3_no_upscale_bottom(self, svc, tmp_output_path):
        """Нижнее фото уже верхних — не апскейлится."""
        p1 = _make_test_image(300, 200)
        p2 = _make_test_image(300, 200)
        p3 = _make_test_image(100, 100)  # уже суммарного top_w=600
        try:
            svc.merge([p1, p2, p3], tmp_output_path)
            result = Image.open(tmp_output_path)
            bot = Image.open(p3)
            # Нижнее фото не апскейлено — его ширина в результате остаётся 100
            assert result.width == 600
        finally:
            os.unlink(p1)
            os.unlink(p2)
            os.unlink(p3)


class TestValidation:
    def test_too_few_photos(self, svc, tmp_output_path):
        """Меньше 2 фото — ValueError."""
        p1 = _make_test_image(200, 200)
        try:
            with pytest.raises(ValueError, match="2 или 3"):
                svc.merge([p1], tmp_output_path)
        finally:
            os.unlink(p1)

    def test_too_many_photos(self, svc, tmp_output_path):
        """Больше 3 фото — ValueError."""
        photos = [_make_test_image(200, 200, (i * 80 % 255, 100, 100)) for i in range(4)]
        try:
            with pytest.raises(ValueError, match="2 или 3"):
                svc.merge(photos, tmp_output_path)
        finally:
            for p in photos:
                os.unlink(p)


class TestMaxOutputSide:
    def test_max_side_scales_down(self, svc, tmp_output_path):
        """max_output_side_px ограничивает размер результата."""
        p1 = _make_test_image(2000, 1000)
        p2 = _make_test_image(2000, 1000)
        try:
            svc.merge([p1, p2], tmp_output_path, max_output_side_px=800)
            result = Image.open(tmp_output_path)
            assert max(result.size) <= 800, f"ожидалось ≤800px, получено {result.size}"
        finally:
            os.unlink(p1)
            os.unlink(p2)

    def test_max_side_zero_no_limit(self, svc, tmp_output_path):
        """max_output_side_px=0 не применяет ограничение."""
        p1 = _make_test_image(1000, 500)
        p2 = _make_test_image(1000, 500)
        try:
            svc.merge([p1, p2], tmp_output_path, max_output_side_px=0)
            result = Image.open(tmp_output_path)
            assert result.width == 2000
        finally:
            os.unlink(p1)
            os.unlink(p2)
