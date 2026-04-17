import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "face-id-service"))

from face_id_app.geometry import BBox, compute_crop_bbox_preserve_ratio  # noqa: E402


def test_compute_crop_bbox_preserves_source_ratio():
    img_w, img_h = 1000, 1500  # 2:3
    face = BBox(x=420, y=460, w=160, h=220)
    x1, y1, x2, y2 = compute_crop_bbox_preserve_ratio(
        img_w=img_w,
        img_h=img_h,
        face_bbox=face,
        pad_left=0.35,
        pad_right=0.35,
        pad_top=0.7,
        pad_bottom=0.35,
    )
    crop_w = x2 - x1
    crop_h = y2 - y1
    assert 0 <= x1 < x2 <= img_w
    assert 0 <= y1 < y2 <= img_h
    assert abs((crop_w / crop_h) - (img_w / img_h)) < 0.02


def test_compute_crop_bbox_clamps_to_image_bounds():
    img_w, img_h = 800, 600
    face = BBox(x=5, y=10, w=120, h=160)
    x1, y1, x2, y2 = compute_crop_bbox_preserve_ratio(
        img_w=img_w,
        img_h=img_h,
        face_bbox=face,
        pad_left=2.0,
        pad_right=2.0,
        pad_top=2.0,
        pad_bottom=2.0,
    )
    assert 0 <= x1 < x2 <= img_w
    assert 0 <= y1 < y2 <= img_h
