import os
import time
import urllib.request
from typing import Any

import mediapipe as mp
import numpy as np
from PIL import Image, ImageOps

from face_id_app.config import settings
from face_id_app.geometry import BBox, compute_crop_bbox_preserve_ratio

_MODEL_PATH_CACHE: dict[int, str] = {}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _detect_faces(
    image_rgb: Image.Image,
    *,
    model_selection: int,
    min_detection_confidence: float,
) -> list[dict[str, Any]]:
    from mediapipe.tasks.python import vision

    img_w, img_h = image_rgb.size
    model_path = _ensure_detector_model_file(model_selection)
    image_array = np.array(image_rgb)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=image_array)
    detections: list[dict[str, Any]] = []
    options = vision.FaceDetectorOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=model_path),
        running_mode=vision.RunningMode.IMAGE,
        min_detection_confidence=min_detection_confidence,
    )
    with vision.FaceDetector.create_from_options(options) as detector:
        result = detector.detect(mp_image)
    for det in (result.detections or []):
        box = getattr(det, "bounding_box", None)
        if not box:
            continue
        score = 0.0
        categories = getattr(det, "categories", None) or []
        if categories:
            try:
                score = float(getattr(categories[0], "score", 0.0) or 0.0)
            except Exception:
                score = 0.0
        x_rel = _clamp01(float(getattr(box, "origin_x", 0.0) or 0.0) / float(img_w or 1))
        y_rel = _clamp01(float(getattr(box, "origin_y", 0.0) or 0.0) / float(img_h or 1))
        w_rel = _clamp01(float(getattr(box, "width", 0.0) or 0.0) / float(img_w or 1))
        h_rel = _clamp01(float(getattr(box, "height", 0.0) or 0.0) / float(img_h or 1))
        detections.append(
            {
                "score": score,
                "bbox_rel": {
                    "x": x_rel,
                    "y": y_rel,
                    "w": w_rel,
                    "h": h_rel,
                },
            }
        )
    detections.sort(key=lambda x: x["score"], reverse=True)
    return detections


def _ensure_detector_model_file(model_selection: int) -> str:
    if model_selection in _MODEL_PATH_CACHE and os.path.isfile(_MODEL_PATH_CACHE[model_selection]):
        return _MODEL_PATH_CACHE[model_selection]
    models_dir = str(settings.face_detector_models_dir or "/tmp/mediapipe_models")
    os.makedirs(models_dir, exist_ok=True)
    if model_selection == 0:
        model_name = "blaze_face_short_range.tflite"
        model_url = str(settings.face_detector_short_model_url)
    else:
        model_name = "blaze_face_full_range.tflite"
        model_url = str(settings.face_detector_full_model_url)
    model_path = os.path.join(models_dir, model_name)
    if not os.path.isfile(model_path):
        urllib.request.urlretrieve(model_url, model_path)
    _MODEL_PATH_CACHE[model_selection] = model_path
    return model_path


def process_asset(payload: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    asset_id = str(payload.get("asset_id") or "").strip()
    source_path = str(payload.get("source_path") or "").strip()
    detector_cfg = payload.get("detector_config") if isinstance(payload.get("detector_config"), dict) else {}

    model_selection = _safe_int(detector_cfg.get("model_selection"), 1)
    if model_selection not in (0, 1):
        model_selection = 1
    min_conf = _safe_float(detector_cfg.get("min_detection_confidence"), 0.6)
    min_conf = max(0.0, min(1.0, min_conf))
    max_faces_allowed = max(1, _safe_int(detector_cfg.get("max_faces_allowed"), 1))
    no_face_policy = str(detector_cfg.get("no_face_policy") or "fallback_original").strip().lower()
    multi_face_policy = str(detector_cfg.get("multi_face_policy") or "fail_generation").strip().lower()
    pad_left = max(0.0, _safe_float(detector_cfg.get("crop_pad_left"), 0.55))
    pad_right = max(0.0, _safe_float(detector_cfg.get("crop_pad_right"), 0.55))
    pad_top = max(0.0, _safe_float(detector_cfg.get("crop_pad_top"), 0.7))
    pad_bottom = max(0.0, _safe_float(detector_cfg.get("crop_pad_bottom"), 0.35))

    with Image.open(source_path) as image_raw:
        image = ImageOps.exif_transpose(image_raw).convert("RGB")
    img_w, img_h = image.size
    if (img_w * img_h) > int(settings.max_image_pixels):
        raise ValueError(f"image too large: {img_w}x{img_h}")

    detections = _detect_faces(
        image,
        model_selection=model_selection,
        min_detection_confidence=min_conf,
    )
    faces_detected = len(detections)
    latency_ms = int((time.perf_counter() - started) * 1000)

    base_meta: dict[str, Any] = {
        "latency_ms": latency_ms,
        "model_version": settings.model_version,
    }
    if faces_detected == 0:
        status = "ready_fallback" if no_face_policy == "fallback_original" else "failed_error"
        base_meta["reason"] = "no_face"
        return {
            "asset_id": asset_id,
            "status": status,
            "faces_detected": 0,
            "selected_path": source_path if status == "ready_fallback" else None,
            "source_path": source_path,
            "detector_meta": base_meta,
        }

    if faces_detected > max_faces_allowed:
        if multi_face_policy == "fallback_original":
            status = "ready_fallback"
            selected_path = source_path
            base_meta["reason"] = "multi_face_fallback"
        else:
            status = "failed_multi_face"
            selected_path = None
            base_meta["reason"] = "multi_face"
        return {
            "asset_id": asset_id,
            "status": status,
            "faces_detected": faces_detected,
            "selected_path": selected_path,
            "source_path": source_path,
            "detector_meta": base_meta,
        }

    primary = detections[0]
    rel = primary["bbox_rel"]
    face_bbox = BBox(
        x=float(rel["x"]) * img_w,
        y=float(rel["y"]) * img_h,
        w=max(1.0, float(rel["w"]) * img_w),
        h=max(1.0, float(rel["h"]) * img_h),
    )
    crop_x1, crop_y1, crop_x2, crop_y2 = compute_crop_bbox_preserve_ratio(
        img_w=img_w,
        img_h=img_h,
        face_bbox=face_bbox,
        pad_left=pad_left,
        pad_right=pad_right,
        pad_top=pad_top,
        pad_bottom=pad_bottom,
    )

    out_dir = os.path.join(settings.storage_base_path, settings.output_subdir)
    os.makedirs(out_dir, exist_ok=True)
    processed_path = os.path.join(out_dir, f"{asset_id}.jpg")
    cropped = image.crop((crop_x1, crop_y1, crop_x2, crop_y2))
    cropped.save(processed_path, format="JPEG", quality=95)

    latency_ms = int((time.perf_counter() - started) * 1000)
    meta = {
        "confidence": float(primary.get("score") or 0.0),
        "bbox": {
            "x": int(round(face_bbox.x)),
            "y": int(round(face_bbox.y)),
            "w": int(round(face_bbox.w)),
            "h": int(round(face_bbox.h)),
        },
        "crop_bbox": {
            "x1": crop_x1,
            "y1": crop_y1,
            "x2": crop_x2,
            "y2": crop_y2,
        },
        "latency_ms": latency_ms,
        "model_version": settings.model_version,
    }
    return {
        "asset_id": asset_id,
        "status": "ready",
        "faces_detected": faces_detected,
        "selected_path": processed_path,
        "source_path": source_path,
        "detector_meta": meta,
    }
