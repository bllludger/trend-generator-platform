#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


def _run(cmd: list[str], timeout: int = 120) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"Command failed ({p.returncode}): {' '.join(cmd)}\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}")
    return p.stdout


def _psql_at(query: str, db_container: str, db_user: str, db_name: str) -> str:
    return _run(
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
            "-F",
            "\t",
            "-c",
            query,
        ],
        timeout=120,
    )


def _parse_probe_json(stdout: str) -> dict:
    m = re.search(r"\{[\s\S]*\}\s*$", stdout.strip())
    if not m:
        raise RuntimeError(f"Cannot parse probe JSON from output:\n{stdout}")
    return json.loads(m.group(0))


def _to_host_path(container_path: str, container_root: str, host_root: Path) -> Path:
    p = Path(container_path)
    croot = Path(container_root)
    rel = p.relative_to(croot)
    return host_root / rel


@dataclass
class Row:
    source_original: str
    status: str
    faces_detected: str
    confidence: str
    crop_bbox: str
    before_rel: str | None
    after_rel: str | None
    take_id: str | None = None
    trend_title: str | None = None
    error: str | None = None
    trend_images: list[dict[str, str]] = field(default_factory=list)


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch Face-ID report from bot uploaded source images in DB.")
    parser.add_argument("--db-container", default="ai_slop_2-db-1")
    parser.add_argument("--db-user", default="trends")
    parser.add_argument("--db-name", default="trends")
    parser.add_argument("--api-url", default="http://127.0.0.1:8010")
    parser.add_argument("--storage-root", default="./data/generated_images")
    parser.add_argument("--container-storage-root", default="/data/generated_images")
    parser.add_argument("--callback-host", default="172.18.0.1")
    parser.add_argument("--callback-port", type=int, default=8787)
    parser.add_argument("--report-root", default="./reports/face_id_batch_report")
    parser.add_argument("--limit", type=int, default=0, help="0 = no limit")
    args = parser.parse_args()

    host_storage_root = Path(args.storage_root).resolve()
    report_root = Path(args.report_root).resolve()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = report_root / run_id
    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    q_paths = """
    with p as (
      select distinct jsonb_array_elements_text(input_local_paths) as path
      from takes
      where (case when jsonb_typeof(input_local_paths)='array' then jsonb_array_length(input_local_paths) else 0 end) > 0
    )
    select path from p order by path;
    """
    raw_paths = _psql_at(q_paths, args.db_container, args.db_user, args.db_name)
    paths = [x.strip() for x in raw_paths.splitlines() if x.strip()]
    if args.limit and args.limit > 0:
        paths = paths[: args.limit]

    q_cfg = """
    select
      enabled,
      min_detection_confidence,
      model_selection,
      crop_pad_left,
      crop_pad_right,
      crop_pad_top,
      crop_pad_bottom,
      max_faces_allowed,
      no_face_policy,
      multi_face_policy
    from face_id_settings
    where id = 1;
    """
    cfg_row = _psql_at(q_cfg, args.db_container, args.db_user, args.db_name).strip().split("\t")
    cfg = {
        "enabled": cfg_row[0] if len(cfg_row) > 0 else "",
        "min_detection_confidence": cfg_row[1] if len(cfg_row) > 1 else "",
        "model_selection": cfg_row[2] if len(cfg_row) > 2 else "",
        "crop_pad_left": cfg_row[3] if len(cfg_row) > 3 else "",
        "crop_pad_right": cfg_row[4] if len(cfg_row) > 4 else "",
        "crop_pad_top": cfg_row[5] if len(cfg_row) > 5 else "",
        "crop_pad_bottom": cfg_row[6] if len(cfg_row) > 6 else "",
        "max_faces_allowed": cfg_row[7] if len(cfg_row) > 7 else "",
        "no_face_policy": cfg_row[8] if len(cfg_row) > 8 else "",
        "multi_face_policy": cfg_row[9] if len(cfg_row) > 9 else "",
    }

    q_latest_outputs = """
    with expanded as (
      select
        jsonb_array_elements_text(t.input_local_paths) as source_path,
        t.id as take_id,
        coalesce(tr.emoji, '') as trend_emoji,
        coalesce(tr.name, '') as trend_name,
        t.created_at,
        t.variant_a_preview,
        t.variant_b_preview,
        t.variant_c_preview,
        t.variant_a_original,
        t.variant_b_original,
        t.variant_c_original
      from takes t
      left join trends tr on tr.id = t.trend_id
      where (case when jsonb_typeof(t.input_local_paths)='array' then jsonb_array_length(t.input_local_paths) else 0 end) > 0
        and (
          t.variant_a_preview is not null or t.variant_b_preview is not null or t.variant_c_preview is not null
          or t.variant_a_original is not null or t.variant_b_original is not null or t.variant_c_original is not null
        )
    ),
    ranked as (
      select *,
             row_number() over (partition by source_path order by created_at desc) as rn
      from expanded
    )
    select
      source_path,
      take_id,
      trend_emoji,
      trend_name,
      coalesce(variant_a_preview, ''),
      coalesce(variant_b_preview, ''),
      coalesce(variant_c_preview, ''),
      coalesce(variant_a_original, ''),
      coalesce(variant_b_original, ''),
      coalesce(variant_c_original, '')
    from ranked
    where rn = 1;
    """
    raw_latest = _psql_at(q_latest_outputs, args.db_container, args.db_user, args.db_name)
    latest_outputs: dict[str, dict[str, str]] = {}
    for line in raw_latest.splitlines():
        cols = line.split("\t")
        if len(cols) < 10:
            continue
        source_path = cols[0].strip()
        if not source_path:
            continue
        latest_outputs[source_path] = {
            "take_id": cols[1].strip(),
            "trend_emoji": cols[2].strip(),
            "trend_name": cols[3].strip(),
            "a_preview": cols[4].strip(),
            "b_preview": cols[5].strip(),
            "c_preview": cols[6].strip(),
            "a_original": cols[7].strip(),
            "b_original": cols[8].strip(),
            "c_original": cols[9].strip(),
        }

    rows: list[Row] = []
    ok = 0
    fail = 0
    processed = 0

    for idx, cpath in enumerate(paths, start=1):
        try:
            hpath = _to_host_path(cpath, args.container_storage_root, host_storage_root)
        except Exception:
            fail += 1
            rows.append(
                Row(
                    source_original=cpath,
                    status="skipped_bad_path",
                    faces_detected="",
                    confidence="",
                    crop_bbox="",
                    before_rel=None,
                    after_rel=None,
                    take_id=None,
                    trend_title=None,
                    trend_images=[],
                    error="Cannot map container path to host path",
                )
            )
            continue
        if not hpath.exists():
            fail += 1
            rows.append(
                Row(
                    source_original=cpath,
                    status="missing_source_file",
                    faces_detected="",
                    confidence="",
                    crop_bbox="",
                    before_rel=None,
                    after_rel=None,
                    take_id=None,
                    trend_title=None,
                    trend_images=[],
                    error=f"Missing file: {hpath}",
                )
            )
            continue

        before_ext = hpath.suffix.lower() or ".jpg"
        before_name = f"{idx:04d}_before{before_ext}"
        before_dst = images_dir / before_name
        shutil.copy2(hpath, before_dst)

        cmd = [
            "python3",
            "scripts/face_id_probe.py",
            "--image",
            str(hpath),
            "--api-url",
            args.api_url,
            "--storage-root",
            str(host_storage_root),
            "--container-storage-root",
            args.container_storage_root,
            "--output-dir",
            str(out_dir / "probe_raw"),
            "--callback-host",
            args.callback_host,
            "--callback-port",
            str(args.callback_port),
        ]
        try:
            probe_out = _run(cmd, timeout=180)
            summary = _parse_probe_json(probe_out)
        except Exception as e:
            fail += 1
            rows.append(
                Row(
                    source_original=cpath,
                    status="probe_failed",
                    faces_detected="",
                    confidence="",
                    crop_bbox="",
                    before_rel=str(before_dst.relative_to(out_dir)),
                    after_rel=None,
                    take_id=None,
                    trend_title=None,
                    trend_images=[],
                    error=str(e),
                )
            )
            continue

        processed += 1
        status = str(summary.get("status") or "")
        faces = summary.get("faces_detected")
        meta = summary.get("detector_meta") or {}
        conf = meta.get("confidence")
        crop_bbox = meta.get("crop_bbox")

        after_rel = None
        selected_container = summary.get("selected_path")
        if isinstance(selected_container, str) and selected_container.strip():
            try:
                after_host = _to_host_path(selected_container, args.container_storage_root, host_storage_root)
                if after_host.exists():
                    after_ext = after_host.suffix.lower() or ".jpg"
                    after_name = f"{idx:04d}_after{after_ext}"
                    after_dst = images_dir / after_name
                    shutil.copy2(after_host, after_dst)
                    after_rel = str(after_dst.relative_to(out_dir))
            except Exception:
                after_rel = None

        if status == "ready":
            ok += 1
        else:
            fail += 1

        take_id = None
        trend_title = None
        trend_images: list[dict[str, str]] = []
        latest = latest_outputs.get(cpath)
        if latest:
            take_id = latest.get("take_id") or None
            trend_name = latest.get("trend_name") or ""
            trend_emoji = latest.get("trend_emoji") or ""
            trend_title = f"{trend_emoji} {trend_name}".strip() if (trend_name or trend_emoji) else None

            for slot in ("a", "b", "c"):
                chosen = latest.get(f"{slot}_preview") or latest.get(f"{slot}_original")
                if not chosen:
                    continue
                try:
                    candidate_host = _to_host_path(chosen, args.container_storage_root, host_storage_root)
                except Exception:
                    continue
                if not candidate_host.exists():
                    continue
                ext = candidate_host.suffix.lower() or ".png"
                out_name = f"{idx:04d}_trend_{slot.upper()}{ext}"
                out_file = images_dir / out_name
                shutil.copy2(candidate_host, out_file)
                trend_images.append(
                    {
                        "slot": slot.upper(),
                        "rel": str(out_file.relative_to(out_dir)),
                    }
                )

        rows.append(
            Row(
                source_original=cpath,
                status=status,
                faces_detected="" if faces is None else str(faces),
                confidence="" if conf is None else f"{float(conf):.4f}",
                crop_bbox="" if crop_bbox is None else json.dumps(crop_bbox, ensure_ascii=False),
                before_rel=str(before_dst.relative_to(out_dir)),
                after_rel=after_rel,
                take_id=take_id,
                trend_title=trend_title,
                trend_images=trend_images,
                error=str(meta.get("error") or "") if status != "ready" else None,
            )
        )

    with_trends = sum(1 for r in rows if r.trend_images)
    rows_html = []
    for i, r in enumerate(rows, start=1):
        before_img = f'<img src="{html.escape(r.before_rel)}" alt="before">' if r.before_rel else "<div class='ph'>No before</div>"
        after_img = f'<img src="{html.escape(r.after_rel)}" alt="after">' if r.after_rel else "<div class='ph'>No after</div>"
        err_html = f"<div class='err'>{html.escape(r.error)}</div>" if r.error else ""
        trend_title_html = f'<div class="line"><b>Trend:</b> {html.escape(r.trend_title)}</div>' if r.trend_title else ""
        take_html = f'<div class="line"><b>Take:</b> {html.escape(r.take_id)}</div>' if r.take_id else ""
        trend_cards = []
        for img in r.trend_images:
            trend_cards.append(
                f"""
                <div class="trend-card">
                  <div class="trend-label">Вариант {html.escape(img.get("slot",""))}</div>
                  <img src="{html.escape(img.get("rel",""))}" alt="trend {html.escape(img.get('slot',''))}">
                </div>
                """
            )
        while len(trend_cards) < 3:
            trend_cards.append('<div class="trend-card"><div class="trend-label">—</div><div class="ph">Нет варианта</div></div>')
        rows_html.append(
            f"""
            <section class="case">
              <div class="meta">
                <h2>#{i:04d} · {html.escape(r.status)}</h2>
                <div class="line"><b>Source:</b> {html.escape(r.source_original)}</div>
                <div class="line"><b>Faces:</b> {html.escape(r.faces_detected)} · <b>Confidence:</b> {html.escape(r.confidence)}</div>
                <div class="line"><b>Crop bbox:</b> {html.escape(r.crop_bbox)}</div>
                {take_html}
                {trend_title_html}
                {err_html}
              </div>
              <div class="pair">
                <div class="col">
                  <div class="label">До (исходник)</div>
                  {before_img}
                </div>
                <div class="col">
                  <div class="label">После (Face-ID)</div>
                  {after_img}
                </div>
              </div>
              <div class="trend-block">
                <div class="label">Что видел пользователь (тренд-варианты)</div>
                <div class="trend-grid">
                  {''.join(trend_cards)}
                </div>
              </div>
            </section>
            """
        )

    html_doc = f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Face-ID Batch Report</title>
  <style>
    body {{ font-family: -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Ubuntu,sans-serif; margin: 0; background: #0b1020; color: #f1f5f9; }}
    .wrap {{ max-width: 1400px; margin: 0 auto; padding: 24px; }}
    .head {{ background: linear-gradient(120deg,#1d4ed8,#0ea5e9); border-radius: 16px; padding: 20px; margin-bottom: 20px; }}
    .grid {{ display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 8px 20px; }}
    .case {{ background:#111827; border:1px solid #1f2937; border-radius:14px; padding:16px; margin-bottom:16px; }}
    .meta h2 {{ margin:0 0 8px 0; font-size:20px; }}
    .line {{ opacity:.95; margin:4px 0; word-break: break-all; }}
    .pair {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-top:14px; }}
    .col {{ background:#0f172a; border:1px solid #1e293b; border-radius:12px; padding:10px; }}
    .trend-block {{ margin-top:14px; background:#0f172a; border:1px solid #1e293b; border-radius:12px; padding:10px; }}
    .trend-grid {{ display:grid; grid-template-columns:repeat(3, minmax(0,1fr)); gap:10px; }}
    .trend-card {{ background:#111827; border:1px solid #263245; border-radius:10px; padding:8px; }}
    .trend-label {{ font-size:12px; color:#a5b4fc; margin-bottom:6px; }}
    .label {{ font-size:14px; color:#93c5fd; margin-bottom:8px; }}
    img {{ width:100%; height:auto; border-radius:10px; display:block; }}
    .ph {{ height:240px; display:flex; align-items:center; justify-content:center; background:#1f2937; border-radius:10px; color:#94a3b8; }}
    .err {{ margin-top:8px; color:#fca5a5; white-space: pre-wrap; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="head">
      <h1 style="margin:0 0 10px 0;">Face-ID Batch Report (Before/After)</h1>
      <div class="grid">
        <div><b>Generated:</b> {datetime.now(timezone.utc).isoformat()}</div>
        <div><b>Total unique sources:</b> {len(paths)}</div>
        <div><b>Processed:</b> {processed}</div>
        <div><b>Ready:</b> {ok} · <b>Non-ready/failed:</b> {fail}</div>
        <div><b>Cases with trend outputs:</b> {with_trends}</div>
      </div>
      <h3 style="margin:14px 0 8px 0;">Current Face-ID config (\"текущий промпт\" сервиса)</h3>
      <pre style="margin:0; background:#0f172a; border:1px solid #1e293b; padding:10px; border-radius:10px; overflow:auto;">{html.escape(json.dumps(cfg, ensure_ascii=False, indent=2))}</pre>
    </div>
    {''.join(rows_html)}
  </div>
</body>
</html>
"""
    (out_dir / "report.html").write_text(html_doc, encoding="utf-8")
    (out_dir / "report.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "count_paths": len(paths),
                "processed": processed,
                "ready": ok,
                "failed_or_non_ready": fail,
                "with_trend_outputs": with_trends,
                "face_id_config": cfg,
                "rows": [r.__dict__ for r in rows],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Report created: {out_dir}")
    print(f"HTML: {out_dir / 'report.html'}")
    print(f"JSON: {out_dir / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
