#!/usr/bin/env python3
"""Build private report for inactive (dropped-off) users.

Inactive cohort definition:
- users that have activity signal (events/takes/sessions/payments),
- but have no generated result in takes with status in ('ready', 'partial_fail').
"""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT_DIR / "reports" / "private"
DATA_ROOT = ROOT_DIR / "data" / "generated_images"
OUTPUTS_ROOT = DATA_ROOT / "outputs"
ENV_PATH = ROOT_DIR / ".env"

RESULT_EVENT_NAMES = {"generation_completed", "take_preview_ready", "trend_preview_ready"}


def parse_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip("'").strip('"')
    return out


def run_cmd(args: list[str]) -> str:
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            f"{' '.join(args)}\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )
    return proc.stdout


def detect_db_container() -> str:
    names = [line.strip() for line in run_cmd(["docker", "ps", "--format", "{{.Names}}"]).splitlines() if line.strip()]
    for name in names:
        if "-db-" in name:
            return name
    for name in names:
        if name.endswith("_db_1") or name.endswith("-db-1") or name == "db":
            return name
    raise RuntimeError("Could not detect DB container. Pass --db-container explicitly.")


def query_rows_json(*, db_container: str, db_user: str, db_name: str, sql: str) -> list[dict[str, Any]]:
    wrapped = f"SELECT row_to_json(r) FROM ({sql}) r;"
    out = run_cmd(
        [
            "docker",
            "exec",
            db_container,
            "psql",
            "-U",
            db_user,
            "-d",
            db_name,
            "-At",
            "-P",
            "pager=off",
            "-c",
            wrapped,
        ]
    )
    rows: list[dict[str, Any]] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_url(path: str | None) -> str | None:
    if not path:
        return None
    s = str(path).strip()
    if not s:
        return None
    if s.startswith("/"):
        return s
    return f"/{s}"


def ensure_list(v: Any) -> list[Any]:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


def file_exists_for_url(url: str | None) -> bool:
    if not url:
        return False
    return (ROOT_DIR / url.lstrip("/")).exists()


def infer_hd_url(take_id: str, variant: str | None) -> str | None:
    if not variant:
        return None
    var = variant.upper().strip()
    for ext in ("png", "jpg", "jpeg", "webp"):
        c = OUTPUTS_ROOT / f"{take_id}_{var}_hd.{ext}"
        if c.exists():
            return f"/data/generated_images/outputs/{c.name}"
    return None


def short_user_label(u: dict[str, Any]) -> str:
    username = (u.get("telegram_username") or "").strip()
    if username:
        return f"@{username}"
    tg = (u.get("telegram_id") or "").strip()
    if tg:
        return tg
    return str(u.get("id", "unknown"))


def analyze_dropoff(event_counts: dict[str, int], summary: dict[str, Any], favorites_count: int) -> dict[str, Any]:
    has = lambda ev: event_counts.get(ev, 0) > 0

    reached = {
        "bot_started": has("bot_started"),
        "photo_uploaded": has("photo_uploaded"),
        "trend_viewed": has("trend_viewed"),
        "take_started": has("take_started") or summary["takes_total"] > 0,
        "generation_started": has("generation_started"),
        "generation_result": (
            summary["takes_with_results"] > 0
            or any(has(ev) for ev in RESULT_EVENT_NAMES)
        ),
        "favorite_selected": has("favorite_selected") or has("trend_favorite_selected") or favorites_count > 0,
        "hd_delivered": has("hd_delivered"),
    }

    if reached["generation_result"]:
        stage = "has_result"
        reason = "user reached generated result"
    elif reached["generation_started"]:
        stage = "generation_started_no_result"
        reason = "generation started, but no completed result"
    elif reached["take_started"]:
        stage = "take_started_no_generation"
        reason = "take started, generation not started"
    elif reached["trend_viewed"]:
        stage = "trend_viewed_no_take"
        reason = "trend viewed, no take started"
    elif reached["photo_uploaded"]:
        stage = "photo_uploaded_no_trend"
        reason = "photo uploaded, no trend view/take"
    elif reached["bot_started"]:
        stage = "bot_started_no_photo"
        reason = "bot started, no photo uploaded"
    else:
        stage = "registered_no_flow"
        reason = "no funnel events found"

    return {"stage": stage, "reason": reason, "reached": reached}


def build_data(*, db_container: str, db_user: str, db_name: str) -> dict[str, Any]:
    has_result_exists = (
        "EXISTS ("
        "  SELECT 1 FROM takes tx "
        "  WHERE tx.user_id = u.id AND tx.status IN ('ready', 'partial_fail')"
        ")"
    )
    has_signal_exists = (
        "("
        "EXISTS (SELECT 1 FROM product_events pe WHERE pe.user_id = u.id) "
        "OR EXISTS (SELECT 1 FROM takes tx WHERE tx.user_id = u.id) "
        "OR EXISTS (SELECT 1 FROM sessions sx WHERE sx.user_id = u.id) "
        "OR EXISTS (SELECT 1 FROM payments px WHERE px.user_id = u.id)"
        ")"
    )
    eligible_condition = f"NOT ({has_result_exists}) AND {has_signal_exists}"

    users_sql = f"""
        SELECT
            u.id,
            u.telegram_id,
            u.telegram_username,
            u.telegram_first_name,
            u.telegram_last_name,
            u.subscription_active,
            u.created_at,
            u.updated_at,
            u.traffic_source,
            u.traffic_campaign
        FROM users u
        WHERE {eligible_condition}
        ORDER BY u.created_at ASC
    """
    takes_sql = f"""
        SELECT
            t.id AS take_id,
            t.user_id,
            t.session_id,
            t.take_type,
            t.trend_id,
            tr.name AS trend_name,
            t.custom_prompt,
            t.image_size,
            t.status,
            t.input_local_paths,
            t.copy_reference_path,
            t.variant_a_preview,
            t.variant_b_preview,
            t.variant_c_preview,
            t.variant_a_original,
            t.variant_b_original,
            t.variant_c_original,
            t.error_code,
            t.error_variants,
            t.is_reroll,
            t.is_rescue_photo_replace,
            t.created_at
        FROM takes t
        JOIN users u ON u.id = t.user_id
        LEFT JOIN trends tr ON tr.id = t.trend_id
        WHERE {eligible_condition}
        ORDER BY t.user_id, t.created_at ASC
    """
    events_sql = f"""
        SELECT
            pe.user_id,
            pe.timestamp,
            pe.event_name,
            pe.session_id,
            pe.take_id,
            pe.trend_id,
            pe.properties
        FROM product_events pe
        JOIN users u ON u.id = pe.user_id
        WHERE {eligible_condition}
        ORDER BY pe.user_id, pe.timestamp ASC
    """
    sessions_sql = f"""
        SELECT
            s.id,
            s.user_id,
            s.pack_id,
            s.status,
            s.takes_limit,
            s.takes_used,
            s.hd_limit,
            s.hd_used,
            s.input_photo_path,
            s.created_at,
            s.updated_at
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE {eligible_condition}
        ORDER BY s.user_id, s.created_at ASC
    """
    favorites_sql = f"""
        SELECT
            f.id,
            f.user_id,
            f.session_id,
            f.take_id,
            f.variant,
            f.created_at
        FROM favorites f
        JOIN users u ON u.id = f.user_id
        WHERE {eligible_condition}
        ORDER BY f.user_id, f.created_at ASC
    """
    payments_sql = f"""
        SELECT
            p.id,
            p.user_id,
            p.session_id,
            p.pack_id,
            p.stars_amount,
            p.amount_kopecks,
            p.tokens_granted,
            p.status,
            p.telegram_payment_charge_id,
            p.provider_payment_charge_id,
            p.created_at,
            p.refunded_at
        FROM payments p
        JOIN users u ON u.id = p.user_id
        WHERE {eligible_condition}
        ORDER BY p.user_id, p.created_at ASC
    """

    print("Querying inactive users...")
    users = query_rows_json(db_container=db_container, db_user=db_user, db_name=db_name, sql=users_sql)
    print(f"Loaded users: {len(users)}")
    print("Querying takes/events/sessions/favorites/payments...")
    takes = query_rows_json(db_container=db_container, db_user=db_user, db_name=db_name, sql=takes_sql)
    events = query_rows_json(db_container=db_container, db_user=db_user, db_name=db_name, sql=events_sql)
    sessions = query_rows_json(db_container=db_container, db_user=db_user, db_name=db_name, sql=sessions_sql)
    favorites = query_rows_json(db_container=db_container, db_user=db_user, db_name=db_name, sql=favorites_sql)
    payments = query_rows_json(db_container=db_container, db_user=db_user, db_name=db_name, sql=payments_sql)

    events_by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    takes_by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    sessions_by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    payments_by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    favorites_by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    favorite_by_take: dict[str, dict[str, Any]] = {}
    hd_variant_by_take: dict[str, str] = {}

    for ev in events:
        events_by_user[ev["user_id"]].append(ev)
        if ev.get("event_name") == "hd_delivered":
            take_id = ev.get("take_id")
            variant = (ev.get("properties") or {}).get("variant")
            if take_id and variant:
                hd_variant_by_take[take_id] = str(variant).upper()

    for fav in favorites:
        favorites_by_user[fav["user_id"]].append(fav)
        take_id = fav.get("take_id")
        if take_id:
            favorite_by_take[take_id] = fav

    for s in sessions:
        s["input_photo_url"] = normalize_url(s.get("input_photo_path"))
        sessions_by_user[s["user_id"]].append(s)

    for p in payments:
        payments_by_user[p["user_id"]].append(p)

    for t in takes:
        preview_a = normalize_url(t.get("variant_a_preview"))
        preview_b = normalize_url(t.get("variant_b_preview"))
        preview_c = normalize_url(t.get("variant_c_preview"))
        original_a = normalize_url(t.get("variant_a_original"))
        original_b = normalize_url(t.get("variant_b_original"))
        original_c = normalize_url(t.get("variant_c_original"))
        copy_ref = normalize_url(t.get("copy_reference_path"))
        inputs = [normalize_url(p) for p in ensure_list(t.get("input_local_paths"))]
        inputs = [p for p in inputs if p]

        fav = favorite_by_take.get(t["take_id"])
        selected_variant = str(fav["variant"]).upper() if fav and fav.get("variant") else None
        if not selected_variant and t["take_id"] in hd_variant_by_take:
            selected_variant = hd_variant_by_take[t["take_id"]]

        t["preview_urls"] = [preview_a, preview_b, preview_c]
        t["original_urls"] = [original_a, original_b, original_c]
        t["copy_reference_url"] = copy_ref
        t["input_photo_urls"] = inputs
        t["selected_variant"] = selected_variant
        t["hd_url"] = infer_hd_url(t["take_id"], selected_variant)
        t["preview_count"] = sum(1 for p in (preview_a, preview_b, preview_c) if p)
        t["has_result"] = t.get("status") in ("ready", "partial_fail")
        takes_by_user[t["user_id"]].append(t)

    users_out: list[dict[str, Any]] = []
    global_event_counter: Counter[str] = Counter()
    global_button_counter: Counter[str] = Counter()
    global_dropoff_counter: Counter[str] = Counter()
    global_photo_paths: set[str] = set()
    stage_reach_counts: Counter[str] = Counter()

    for u in users:
        user_id = u["id"]
        user_events = events_by_user.get(user_id, [])
        user_takes = takes_by_user.get(user_id, [])
        user_sessions = sessions_by_user.get(user_id, [])
        user_favorites = favorites_by_user.get(user_id, [])
        user_payments = payments_by_user.get(user_id, [])

        event_counter: Counter[str] = Counter()
        button_counter: Counter[str] = Counter()
        trend_counter: Counter[str] = Counter()
        timeline: list[dict[str, Any]] = []

        for ev in user_events:
            event_name = ev.get("event_name") or "unknown"
            event_counter[event_name] += 1
            global_event_counter[event_name] += 1

            if event_name == "button_click":
                button_id = (ev.get("properties") or {}).get("button_id")
                if button_id:
                    button_counter[str(button_id)] += 1
                    global_button_counter[str(button_id)] += 1

            timeline.append(
                {
                    "timestamp": ev.get("timestamp"),
                    "event_name": event_name,
                    "session_id": ev.get("session_id"),
                    "take_id": ev.get("take_id"),
                    "trend_id": ev.get("trend_id"),
                    "properties": ev.get("properties") or {},
                }
            )

        photos_map: dict[str, dict[str, Any]] = {}
        for t in user_takes:
            trend_name = t.get("trend_name")
            if trend_name:
                trend_counter[str(trend_name)] += 1
            for p in t.get("input_photo_urls", []):
                global_photo_paths.add(p)
                row = photos_map.get(p)
                if not row:
                    row = {
                        "url": p,
                        "exists": file_exists_for_url(p),
                        "used_in_take_ids": [],
                        "used_in_trends": [],
                    }
                    photos_map[p] = row
                row["used_in_take_ids"].append(t["take_id"])
                if trend_name:
                    row["used_in_trends"].append(trend_name)

        for s in user_sessions:
            p = s.get("input_photo_url")
            if not p:
                continue
            global_photo_paths.add(p)
            if p not in photos_map:
                photos_map[p] = {
                    "url": p,
                    "exists": file_exists_for_url(p),
                    "used_in_take_ids": [],
                    "used_in_trends": [],
                }

        photos = sorted(photos_map.values(), key=lambda x: x["url"])
        for ph in photos:
            ph["uses_count"] = len(ph["used_in_take_ids"])
            ph["used_in_trends"] = sorted(set(ph["used_in_trends"]))

        takes_total = len(user_takes)
        takes_ready = sum(1 for t in user_takes if t.get("status") == "ready")
        takes_partial = sum(1 for t in user_takes if t.get("status") == "partial_fail")
        takes_failed = sum(1 for t in user_takes if t.get("status") == "failed")
        takes_with_results = sum(1 for t in user_takes if t.get("has_result"))
        selected_count = sum(1 for t in user_takes if t.get("selected_variant"))
        hd_count = sum(1 for t in user_takes if t.get("hd_url"))
        generated_count = event_counter.get("generation_started", 0)
        result_events = sum(event_counter.get(e, 0) for e in RESULT_EVENT_NAMES)

        summary = {
            "takes_total": takes_total,
            "takes_ready": takes_ready,
            "takes_partial_fail": takes_partial,
            "takes_failed": takes_failed,
            "takes_with_results": takes_with_results,
            "selected_variants": selected_count,
            "hd_delivered_files": hd_count,
            "sessions_count": len(user_sessions),
            "payments_count": len(user_payments),
            "favorites_count": len(user_favorites),
            "events_count": len(user_events),
            "generated_count": generated_count,
            "result_events_count": result_events,
            "photos_count": len(photos),
            "first_event_at": user_events[0]["timestamp"] if user_events else None,
            "last_event_at": user_events[-1]["timestamp"] if user_events else None,
            "first_take_at": user_takes[0]["created_at"] if user_takes else None,
            "last_take_at": user_takes[-1]["created_at"] if user_takes else None,
        }

        dropoff = analyze_dropoff(dict(event_counter), summary, len(user_favorites))
        global_dropoff_counter[dropoff["stage"]] += 1
        for stage_name, is_reached in dropoff["reached"].items():
            if is_reached:
                stage_reach_counts[stage_name] += 1

        users_out.append(
            {
                "profile": {
                    **u,
                    "display_name": short_user_label(u),
                },
                "summary": summary,
                "dropoff": dropoff,
                "event_counts": dict(event_counter),
                "button_counts": dict(button_counter),
                "trend_counts": dict(trend_counter),
                "photos": photos,
                "takes": user_takes,
                "events": user_events,
                "timeline": timeline,
                "sessions": user_sessions,
                "favorites": user_favorites,
                "payments": user_payments,
            }
        )

    users_out.sort(
        key=lambda x: (
            x["profile"].get("telegram_username") or "",
            x["profile"].get("telegram_id") or "",
            x["profile"].get("id") or "",
        )
    )

    global_stats = {
        "users_count": len(users_out),
        "takes_total": sum(u["summary"]["takes_total"] for u in users_out),
        "takes_with_results": sum(u["summary"]["takes_with_results"] for u in users_out),
        "takes_failed": sum(u["summary"]["takes_failed"] for u in users_out),
        "selected_variants": sum(u["summary"]["selected_variants"] for u in users_out),
        "hd_delivered_files": sum(u["summary"]["hd_delivered_files"] for u in users_out),
        "payments_count": sum(u["summary"]["payments_count"] for u in users_out),
        "events_total": sum(u["summary"]["events_count"] for u in users_out),
        "generated_count_total": sum(u["summary"]["generated_count"] for u in users_out),
        "result_events_count_total": sum(u["summary"]["result_events_count"] for u in users_out),
        "unique_input_photos": len(global_photo_paths),
        "top_events": global_event_counter.most_common(20),
        "top_buttons": global_button_counter.most_common(20),
        "dropoff_by_stage": global_dropoff_counter.most_common(),
        "stage_reach_counts": dict(stage_reach_counts),
    }

    return {
        "meta": {
            "generated_at": now_utc_iso(),
            "root_dir": str(ROOT_DIR),
            "db_container": db_container,
            "cohort": "inactive",
            "scope": "users with activity signal and without generated result (ready/partial_fail)",
        },
        "global_stats": global_stats,
        "users": users_out,
    }


def build_html(json_filename: str) -> str:
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Private Inactive Users Report</title>
  <style>
    :root {{
      --bg: #0f1418;
      --panel: #182128;
      --panel-2: #1e2a33;
      --line: #2a3945;
      --text: #dbe7ef;
      --muted: #9cb2c2;
      --accent: #4ec1a3;
      --warn: #e6b85f;
      --bad: #e27979;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", Arial, sans-serif;
      background: linear-gradient(180deg, #0f1418 0%, #0b1014 100%);
      color: var(--text);
    }}
    .layout {{
      display: grid;
      grid-template-columns: 360px 1fr;
      min-height: 100vh;
    }}
    .sidebar {{
      border-right: 1px solid var(--line);
      background: #131b21;
      padding: 14px;
      position: sticky;
      top: 0;
      height: 100vh;
      overflow: auto;
    }}
    .main {{ padding: 18px; overflow: auto; }}
    h1, h2, h3 {{ margin: 0 0 10px; }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px;
    }}
    .grid {{ display: grid; gap: 12px; }}
    .stats {{ grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); margin-bottom: 12px; }}
    .s {{ background: var(--panel-2); border: 1px solid var(--line); border-radius: 10px; padding: 10px; }}
    .s .n {{ font-size: 24px; font-weight: 700; margin-bottom: 4px; }}
    .s .l {{ color: var(--muted); font-size: 12px; }}
    .muted {{ color: var(--muted); font-size: 13px; }}
    .small {{ font-size: 12px; color: var(--muted); }}
    input {{
      width: 100%;
      background: #0f151a;
      color: var(--text);
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 8px 10px;
    }}
    .section {{ margin-top: 12px; }}
    .chips {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }}
    .chip {{
      font-size: 11px;
      border: 1px solid var(--line);
      padding: 2px 8px;
      border-radius: 999px;
      color: var(--muted);
      background: #101820;
    }}
    .user-list {{ margin-top: 12px; display: grid; gap: 8px; }}
    .user-btn {{
      width: 100%;
      text-align: left;
      background: #0f151a;
      border: 1px solid var(--line);
      color: var(--text);
      border-radius: 10px;
      padding: 8px 10px;
      cursor: pointer;
    }}
    .user-btn.active {{ border-color: var(--accent); background: #10201d; }}
    .photos {{ grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); }}
    .photo {{
      background: var(--panel-2);
      border: 1px solid var(--line);
      border-radius: 12px;
      overflow: hidden;
    }}
    .photo img {{
      width: 100%;
      aspect-ratio: 4 / 5;
      object-fit: cover;
      display: block;
      background: #0e1418;
    }}
    .photo .b {{ padding: 8px; font-size: 12px; }}
    .takes {{ grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); }}
    .take {{
      background: var(--panel-2);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px;
    }}
    .preview-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 6px;
      margin-top: 8px;
    }}
    .preview-grid img {{
      width: 100%;
      aspect-ratio: 1 / 1;
      object-fit: cover;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: #0e1418;
    }}
    .empty {{
      min-height: 66px;
      border: 1px dashed var(--line);
      border-radius: 8px;
      font-size: 11px;
      color: var(--muted);
      display: flex;
      align-items: center;
      justify-content: center;
      text-align: center;
      padding: 6px;
    }}
    .timeline {{
      display: grid;
      gap: 8px;
      max-height: 420px;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 8px;
      background: var(--panel-2);
    }}
    .timeline-item {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 8px;
      background: #141f27;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
      background: var(--panel-2);
      border: 1px solid var(--line);
      border-radius: 10px;
      overflow: hidden;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 7px 8px;
      vertical-align: top;
      text-align: left;
    }}
    th {{ color: var(--muted); font-weight: 600; }}
    code {{
      font-size: 11px;
      background: #101a21;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 1px 4px;
      word-break: break-all;
    }}
    .ok {{ color: var(--accent); }}
    .warn {{ color: var(--warn); }}
    .bad {{ color: var(--bad); }}
    @media (max-width: 1100px) {{
      .layout {{ grid-template-columns: 1fr; }}
      .sidebar {{ position: static; height: auto; }}
    }}
  </style>
</head>
<body>
  <div class="layout">
    <aside class="sidebar">
      <h2>Inactive Cohort</h2>
      <div class="small" id="meta"></div>
      <div class="section">
        <input id="search" type="text" placeholder="Поиск: username / telegram_id / user_id" />
      </div>
      <div class="section card">
        <div class="small">Глобально</div>
        <div class="chips" id="global-stats"></div>
      </div>
      <div class="section card">
        <div class="small">Drop-off stages</div>
        <div class="chips" id="dropoff-stats"></div>
      </div>
      <div class="section card">
        <div class="small">Топ событий</div>
        <div class="chips" id="top-events"></div>
      </div>
      <div class="section user-list" id="users-list"></div>
    </aside>
    <main class="main">
      <div id="content" class="card">Загрузка...</div>
    </main>
  </div>

  <script>
    const dataUrl = "{json_filename}";
    const state = {{ data: null, users: [], filtered: [], selectedUserId: null }};
    const esc = (v) => String(v ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
    const fmtTs = (s) => {{
      if (!s) return "-";
      const d = new Date(s);
      if (Number.isNaN(d.getTime())) return s;
      return d.toISOString().replace("T", " ").replace(".000Z", "Z");
    }};
    const statusCls = (s) => s === "ready" ? "ok" : (s === "partial_fail" ? "warn" : (s === "failed" ? "bad" : ""));

    function userSearchText(u) {{
      const p = u.profile || {{}};
      return [p.id, p.telegram_id, p.telegram_username, p.telegram_first_name, p.telegram_last_name, p.display_name]
        .filter(Boolean).join(" ").toLowerCase();
    }}

    function renderGlobal() {{
      const d = state.data;
      document.getElementById("meta").innerHTML =
        `Сгенерировано: ${{esc(fmtTs(d.meta.generated_at))}}<br>Scope: ${{esc(d.meta.scope)}}`;

      const gs = d.global_stats;
      const stats = [
        ["Users", gs.users_count],
        ["Takes", gs.takes_total],
        ["Failed takes", gs.takes_failed],
        ["Gen started", gs.generated_count_total],
        ["Result events", gs.result_events_count_total],
        ["Payments", gs.payments_count],
        ["Events", gs.events_total],
        ["Photos", gs.unique_input_photos]
      ];
      document.getElementById("global-stats").innerHTML = stats
        .map(([k, v]) => `<span class="chip">${{esc(k)}}: <strong>${{esc(v)}}</strong></span>`)
        .join("");

      document.getElementById("top-events").innerHTML = (gs.top_events || [])
        .slice(0, 10)
        .map(([k, v]) => `<span class="chip">${{esc(k)}}: <strong>${{esc(v)}}</strong></span>`)
        .join("");

      document.getElementById("dropoff-stats").innerHTML = (gs.dropoff_by_stage || [])
        .map(([k, v]) => `<span class="chip">${{esc(k)}}: <strong>${{esc(v)}}</strong></span>`)
        .join("");
    }}

    function applyFilter() {{
      const q = (document.getElementById("search").value || "").trim().toLowerCase();
      state.filtered = !q ? [...state.users] : state.users.filter((u) => userSearchText(u).includes(q));
      renderUsersList();
      if (!state.filtered.find((u) => u.profile.id === state.selectedUserId)) {{
        state.selectedUserId = state.filtered[0]?.profile?.id || null;
      }}
      renderUserDetails();
    }}

    function renderUsersList() {{
      const root = document.getElementById("users-list");
      root.innerHTML = "";
      state.filtered.forEach((u) => {{
        const p = u.profile || {{}};
        const s = u.summary || {{}};
        const d = u.dropoff || {{}};
        const btn = document.createElement("button");
        btn.className = "user-btn" + (p.id === state.selectedUserId ? " active" : "");
        btn.innerHTML =
          `<div><strong>${{esc(p.display_name || p.id)}}</strong></div>` +
          `<div class="small">drop: ${{esc(d.stage || "-")}}</div>` +
          `<div class="small">events: ${{esc(s.events_count || 0)}} | takes: ${{esc(s.takes_total || 0)}} | gen_started: ${{esc(s.generated_count || 0)}}</div>`;
        btn.onclick = () => {{
          state.selectedUserId = p.id;
          renderUsersList();
          renderUserDetails();
        }};
        root.appendChild(btn);
      }});
      if (!state.filtered.length) {{
        root.innerHTML = '<div class="small">Ничего не найдено</div>';
      }}
    }}

    function previewsHtml(arr) {{
      const cells = (arr || []).map((p, idx) => {{
        if (!p) return `<div class="empty">${{idx === 0 ? "A" : idx === 1 ? "B" : "C"}} нет</div>`;
        return `<img src="${{esc(p)}}" loading="lazy" alt="preview" />`;
      }});
      while (cells.length < 3) cells.push('<div class="empty">нет</div>');
      return cells.slice(0, 3).join("");
    }}

    function renderUserDetails() {{
      const root = document.getElementById("content");
      const user = state.users.find((u) => u.profile.id === state.selectedUserId);
      if (!user) {{
        root.innerHTML = "Пользователь не выбран";
        return;
      }}

      const p = user.profile || {{}};
      const s = user.summary || {{}};
      const d = user.dropoff || {{}};

      const timelineHtml = (user.timeline || [])
        .slice()
        .reverse()
        .slice(0, 300)
        .map((ev) => {{
          const props = JSON.stringify(ev.properties || {{}});
          return `<div class="timeline-item">
            <div><strong>${{esc(fmtTs(ev.timestamp))}}</strong> • ${{esc(ev.event_name)}}</div>
            <div class="small">session: <code>${{esc(ev.session_id || "")}}</code> | take: <code>${{esc(ev.take_id || "")}}</code> | trend: <code>${{esc(ev.trend_id || "")}}</code></div>
            <div class="small"><code>${{esc(props)}}</code></div>
          </div>`;
        }}).join("");

      const eventRows = (user.events || [])
        .slice()
        .reverse()
        .slice(0, 500)
        .map((ev) => {{
          const props = JSON.stringify(ev.properties || {{}});
          return `<tr>
            <td>${{esc(fmtTs(ev.timestamp))}}</td>
            <td>${{esc(ev.event_name)}}</td>
            <td><code>${{esc(ev.session_id || "")}}</code></td>
            <td><code>${{esc(ev.take_id || "")}}</code></td>
            <td><code>${{esc(props)}}</code></td>
          </tr>`;
        }}).join("");

      const photosHtml = (user.photos || []).map((ph) => `
        <article class="photo">
          <img src="${{esc(ph.url)}}" loading="lazy" alt="photo" />
          <div class="b">
            <div><strong>${{esc(ph.url.split("/").pop())}}</strong></div>
            <div class="small">uses: ${{esc(ph.uses_count)}} | exists: ${{esc(ph.exists)}}</div>
            <div class="small">trends: ${{esc((ph.used_in_trends || []).slice(0, 4).join(", "))}}</div>
          </div>
        </article>
      `).join("");

      const takesHtml = (user.takes || []).slice().reverse().map((t) => {{
        const input = (t.input_photo_urls || [])[0];
        const hd = t.hd_url
          ? `<div class="small">HD: <a href="${{esc(t.hd_url)}}" target="_blank" rel="noopener">open</a></div>`
          : `<div class="small">HD: -</div>`;
        return `<article class="take">
          <div><strong>${{esc(t.trend_name || t.take_type || "take")}}</strong></div>
          <div class="small">take_id: <code>${{esc(t.take_id)}}</code></div>
          <div class="small">time: ${{esc(fmtTs(t.created_at))}}</div>
          <div class="small">status: <span class="${{statusCls(t.status || "")}}">${{esc(t.status || "-")}}</span> | previews: ${{esc(t.preview_count || 0)}}</div>
          <div class="small">selected_variant: ${{esc(t.selected_variant || "-")}}</div>
          ${{hd}}
          ${{input ? `<div class="small">input: <a href="${{esc(input)}}" target="_blank" rel="noopener">${{esc(input.split("/").pop())}}</a></div>` : ""}}
          ${{t.custom_prompt ? `<div class="small">custom_prompt: <code>${{esc(t.custom_prompt)}}</code></div>` : ""}}
          ${{t.error_code ? `<div class="small bad">error_code: ${{esc(t.error_code)}}</div>` : ""}}
          <div class="preview-grid">${{previewsHtml(t.preview_urls)}}</div>
        </article>`;
      }}).join("");

      const buttonChips = Object.entries(user.button_counts || {{}})
        .sort((a, b) => b[1] - a[1])
        .slice(0, 20)
        .map(([k, v]) => `<span class="chip">${{esc(k)}}: <strong>${{esc(v)}}</strong></span>`)
        .join("");

      const eventChips = Object.entries(user.event_counts || {{}})
        .sort((a, b) => b[1] - a[1])
        .slice(0, 20)
        .map(([k, v]) => `<span class="chip">${{esc(k)}}: <strong>${{esc(v)}}</strong></span>`)
        .join("");

      const reachedChips = Object.entries(d.reached || {{}})
        .map(([k, v]) => `<span class="chip">${{esc(k)}}: <strong>${{esc(v ? "yes" : "no")}}</strong></span>`)
        .join("");

      root.innerHTML = `
        <h1>${{esc(p.display_name || p.id)}}</h1>
        <div class="muted">
          user_id: <code>${{esc(p.id)}}</code> |
          telegram_id: <code>${{esc(p.telegram_id || "")}}</code> |
          username: <code>${{esc(p.telegram_username || "")}}</code>
        </div>
        <div class="muted">
          created: ${{esc(fmtTs(p.created_at))}} | updated: ${{esc(fmtTs(p.updated_at))}} |
          source: <code>${{esc(p.traffic_source || "")}}</code>
        </div>

        <section class="section card">
          <h3>Drop-off analysis</h3>
          <div class="small">stage: <strong>${{esc(d.stage || "-")}}</strong></div>
          <div class="small">reason: ${{esc(d.reason || "-")}}</div>
          <div class="chips">${{reachedChips}}</div>
        </section>

        <section class="section grid stats">
          <div class="s"><div class="n">${{esc(s.events_count || 0)}}</div><div class="l">Events</div></div>
          <div class="s"><div class="n">${{esc(s.generated_count || 0)}}</div><div class="l">Generation started</div></div>
          <div class="s"><div class="n">${{esc(s.result_events_count || 0)}}</div><div class="l">Result events</div></div>
          <div class="s"><div class="n">${{esc(s.takes_total || 0)}}</div><div class="l">Takes total</div></div>
          <div class="s"><div class="n">${{esc(s.takes_failed || 0)}}</div><div class="l">Failed takes</div></div>
          <div class="s"><div class="n">${{esc(s.payments_count || 0)}}</div><div class="l">Payments</div></div>
          <div class="s"><div class="n">${{esc(s.photos_count || 0)}}</div><div class="l">Input photos</div></div>
          <div class="s"><div class="n">${{esc(s.sessions_count || 0)}}</div><div class="l">Sessions</div></div>
        </section>

        <section class="section card">
          <h3>Buttons</h3>
          <div class="chips">${{buttonChips || '<span class="small">no button_click events</span>'}}</div>
        </section>

        <section class="section card">
          <h3>Event counts</h3>
          <div class="chips">${{eventChips || '<span class="small">no events</span>'}}</div>
        </section>

        <section class="section card">
          <h3>Timeline (latest 300 events)</h3>
          <div class="timeline">${{timelineHtml || '<div class="small">No timeline events</div>'}}</div>
        </section>

        <section class="section card">
          <h3>Input photos</h3>
          <div class="grid photos">${{photosHtml || '<div class="small">No photos linked from takes/sessions</div>'}}</div>
        </section>

        <section class="section card">
          <h3>Takes</h3>
          <div class="grid takes">${{takesHtml || '<div class="small">No takes</div>'}}</div>
        </section>

        <section class="section card">
          <h3>Raw events (latest 500)</h3>
          <div style="overflow:auto;">
            <table>
              <thead><tr><th>timestamp</th><th>event_name</th><th>session_id</th><th>take_id</th><th>properties</th></tr></thead>
              <tbody>${{eventRows}}</tbody>
            </table>
          </div>
        </section>
      `;
    }}

    async function init() {{
      const resp = await fetch(dataUrl, {{ cache: "no-store" }});
      if (!resp.ok) {{
        document.getElementById("content").textContent = "Не удалось загрузить JSON: " + resp.status;
        return;
      }}
      state.data = await resp.json();
      state.users = state.data.users || [];
      state.filtered = [...state.users];
      state.selectedUserId = state.users[0]?.profile?.id || null;
      renderGlobal();
      renderUsersList();
      renderUserDetails();
      document.getElementById("search").addEventListener("input", applyFilter);
    }}
    init().catch((err) => {{
      document.getElementById("content").textContent = "Ошибка: " + err;
    }});
  </script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Build private inactive-users report.")
    parser.add_argument("--db-container", default="", help="Postgres docker container name.")
    parser.add_argument("--db-user", default="", help="Postgres user (default from .env or trends).")
    parser.add_argument("--db-name", default="", help="Postgres database (default from .env or trends).")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for HTML/JSON output.")
    args = parser.parse_args()

    env = parse_env(ENV_PATH)
    db_container = args.db_container or detect_db_container()
    db_user = args.db_user or env.get("POSTGRES_USER", "trends")
    db_name = args.db_name or env.get("POSTGRES_DB", "trends")

    print(f"Using DB container={db_container}, db={db_name}, user={db_user}")
    payload = build_data(db_container=db_container, db_user=db_user, db_name=db_name)

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    token = secrets.token_hex(4)
    base = f"users_inactive_activity_{ts}_{token}"
    json_path = output_dir / f"{base}.json"
    html_path = output_dir / f"{base}.html"

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(build_html(json_path.name), encoding="utf-8")

    print("\nDone.")
    print(f"HTML: {html_path}")
    print(f"JSON: {json_path}")
    print("\nRecommended secure preview (on VPS):")
    print(f"  cd {ROOT_DIR}")
    print("  python3 -m http.server 8788 --bind 127.0.0.1")
    print(f"  open via SSH tunnel: http://127.0.0.1:8788/reports/private/{html_path.name}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        raise SystemExit(130)
