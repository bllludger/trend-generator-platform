"""
Analyze user-uploaded photo for product analytics (input_photo_analyzed event).

Returns resolution, optional blur/face metrics. Stubs for face/likeness
can be replaced with opencv or external API later.
"""
import logging
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)


def analyze_input_photo(image_path: str) -> dict:
    """
    Analyze image for analytics. Returns dict suitable for product_events properties.

    Keys: resolution (e.g. "1024x768"), faces_detected, blur_score (0-1),
    lighting_score (0-1), glasses_detected, beard_detected, occlusion_detected, head_angle.
    """
    result = {
        "resolution": None,
        "faces_detected": 0,
        "blur_score": 0.0,
        "lighting_score": 0.5,
        "glasses_detected": False,
        "beard_detected": False,
        "occlusion_detected": False,
        "head_angle": None,
    }
    path = Path(image_path)
    if not path.exists():
        logger.warning("input_photo_analyzer: file not found %s", image_path)
        return result
    try:
        with Image.open(path) as img:
            w, h = img.size
            result["resolution"] = f"{w}x{h}"
    except Exception as e:
        logger.warning("input_photo_analyzer: open failed %s: %s", image_path, e)
        return result
    # Optional: add blur via numpy/opencv if available; keep stub for now
    return result
