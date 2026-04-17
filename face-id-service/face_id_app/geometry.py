from dataclasses import dataclass


@dataclass
class BBox:
    x: float
    y: float
    w: float
    h: float


def _clamp_box_to_image(
    *,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    img_w: float,
    img_h: float,
) -> tuple[float, float, float, float]:
    if x1 < 0:
        x2 -= x1
        x1 = 0
    if y1 < 0:
        y2 -= y1
        y1 = 0
    if x2 > img_w:
        shift = x2 - img_w
        x1 -= shift
        x2 = img_w
    if y2 > img_h:
        shift = y2 - img_h
        y1 -= shift
        y2 = img_h
    x1 = max(0.0, x1)
    y1 = max(0.0, y1)
    x2 = min(img_w, x2)
    y2 = min(img_h, y2)
    return x1, y1, x2, y2


def compute_crop_bbox_preserve_ratio(
    *,
    img_w: int,
    img_h: int,
    face_bbox: BBox,
    pad_left: float,
    pad_right: float,
    pad_top: float,
    pad_bottom: float,
) -> tuple[int, int, int, int]:
    """
    Expand face bbox by pads and then fit crop window to source image ratio.
    Returns (x1, y1, x2, y2) in pixel coordinates for PIL.Image.crop.
    """
    bw = max(1.0, face_bbox.w)
    bh = max(1.0, face_bbox.h)
    ex1 = face_bbox.x - (bw * max(0.0, pad_left))
    ey1 = face_bbox.y - (bh * max(0.0, pad_top))
    ex2 = face_bbox.x + bw + (bw * max(0.0, pad_right))
    ey2 = face_bbox.y + bh + (bh * max(0.0, pad_bottom))

    ew = max(1.0, ex2 - ex1)
    eh = max(1.0, ey2 - ey1)
    target_ratio = max(1e-9, img_w / img_h)
    current_ratio = ew / eh

    if current_ratio < target_ratio:
        ew = eh * target_ratio
    elif current_ratio > target_ratio:
        eh = ew / target_ratio

    cx = (ex1 + ex2) / 2.0
    cy = (ey1 + ey2) / 2.0

    x1 = cx - (ew / 2.0)
    x2 = cx + (ew / 2.0)
    y1 = cy - (eh / 2.0)
    y2 = cy + (eh / 2.0)
    x1, y1, x2, y2 = _clamp_box_to_image(x1=x1, y1=y1, x2=x2, y2=y2, img_w=float(img_w), img_h=float(img_h))

    # Final integer-safe crop.
    ix1 = int(round(x1))
    iy1 = int(round(y1))
    ix2 = int(round(x2))
    iy2 = int(round(y2))
    if ix2 <= ix1:
        ix2 = min(img_w, ix1 + 1)
    if iy2 <= iy1:
        iy2 = min(img_h, iy1 + 1)
    ix1 = max(0, min(ix1, img_w - 1))
    iy1 = max(0, min(iy1, img_h - 1))
    ix2 = max(ix1 + 1, min(ix2, img_w))
    iy2 = max(iy1 + 1, min(iy2, img_h))
    return ix1, iy1, ix2, iy2
