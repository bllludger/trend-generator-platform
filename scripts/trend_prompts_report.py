#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def _run(cmd: list[str], timeout: int = 120) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(
            f"Command failed ({p.returncode}): {' '.join(cmd)}\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}"
        )
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


def _build_trend_prompt(scene_prompt: str, system_prompt: str, prompt_sections_raw: str) -> str:
    trend_parts: list[str] = []
    try:
        parsed = json.loads(prompt_sections_raw) if prompt_sections_raw else []
        if isinstance(parsed, list):
            sections = sorted(parsed, key=lambda x: (x or {}).get("order", 0))
            for s in sections:
                if not isinstance(s, dict):
                    continue
                if not s.get("enabled"):
                    continue
                content = str(s.get("content") or "").strip()
                if content:
                    trend_parts.append(content)
    except Exception:
        trend_parts = []

    trend_prompt = "\n\n".join(trend_parts).strip()
    if not trend_prompt:
        trend_prompt = (scene_prompt or system_prompt or "").strip()
    return trend_prompt


def main() -> int:
    parser = argparse.ArgumentParser(description="Export all trends and prompts to a standalone HTML report.")
    parser.add_argument("--db-container", default="ai_slop_2-db-1")
    parser.add_argument("--db-user", default="trends")
    parser.add_argument("--db-name", default="trends")
    parser.add_argument("--report-root", default="./reports/trend_prompts_report")
    args = parser.parse_args()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.report_root).resolve() / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    q_settings = """
    select
      coalesce(prompt_input, ''),
      coalesce(prompt_task, ''),
      coalesce(prompt_input_enabled, true),
      coalesce(prompt_task_enabled, true)
    from generation_prompt_settings
    where id = 2
    limit 1;
    """
    raw_settings = _psql_at(q_settings, args.db_container, args.db_user, args.db_name).strip()
    s_cols = raw_settings.split("\t") if raw_settings else []
    prompt_input = (s_cols[0] if len(s_cols) > 0 else "").strip()
    prompt_task = (s_cols[1] if len(s_cols) > 1 else "").strip()
    prompt_input_enabled = (s_cols[2] if len(s_cols) > 2 else "t").strip().lower() in ("t", "true", "1", "yes")
    prompt_task_enabled = (s_cols[3] if len(s_cols) > 3 else "t").strip().lower() in ("t", "true", "1", "yes")

    if not prompt_input_enabled:
        prompt_input = ""
    if not prompt_task_enabled:
        prompt_task = ""

    q_trends = """
    select
      t.id,
      coalesce(t.emoji, ''),
      coalesce(t.name, ''),
      coalesce(t.scene_prompt, ''),
      coalesce(t.system_prompt, ''),
      coalesce(t.prompt_sections::text, '[]'),
      coalesce(t.is_active, true),
      coalesce(t.order_index, 0)
    from trends t
    order by t.is_active desc, t.order_index asc, t.created_at asc;
    """
    raw_trends = _psql_at(q_trends, args.db_container, args.db_user, args.db_name)
    items: list[dict] = []
    for line in raw_trends.splitlines():
        cols = line.split("\t")
        if len(cols) < 8:
            continue
        trend_id, emoji, name, scene_prompt, system_prompt, prompt_sections_raw, is_active, order_index = cols[:8]
        trend_prompt = _build_trend_prompt(scene_prompt, system_prompt, prompt_sections_raw)

        blocks = []
        if prompt_input:
            blocks.append(prompt_input)
        if trend_prompt:
            blocks.append(trend_prompt)
        full_prompt = "\n\n".join(blocks).strip()

        items.append(
            {
                "trend_id": trend_id,
                "emoji": emoji,
                "name": name,
                "is_active": str(is_active).lower() in ("t", "true", "1", "yes"),
                "order_index": int(order_index) if str(order_index).strip().isdigit() else 0,
                "trend_prompt": trend_prompt,
                "full_prompt": full_prompt,
            }
        )

    cards = []
    for idx, item in enumerate(items, start=1):
        title = f"{item['emoji']} {item['name']}".strip() or "(без названия)"
        status = "active" if item["is_active"] else "inactive"
        cards.append(
            f"""
            <section class="card">
              <div class="meta">
                <div class="idx">#{idx:03d}</div>
                <h2>{html.escape(title)}</h2>
                <span class="badge {status}">{status}</span>
              </div>
              <div class="sub">trend_id: <code>{html.escape(item["trend_id"])}</code> · order_index: <code>{item["order_index"]}</code></div>
              <div class="prompt-wrap">
                <div class="prompt-title">Effective prompt (1:1 для release генерации)</div>
                <pre>{html.escape(item["full_prompt"])}</pre>
              </div>
            </section>
            """
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    html_doc = f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Trends Prompts Export</title>
  <style>
    :root {{
      --bg: #0b1020;
      --card: #111827;
      --muted: #94a3b8;
      --text: #e2e8f0;
      --accent: #38bdf8;
      --line: #1f2937;
    }}
    body {{ margin: 0; background: var(--bg); color: var(--text); font-family: -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Ubuntu,sans-serif; }}
    .wrap {{ max-width: 1300px; margin: 0 auto; padding: 24px; }}
    .head {{ background: linear-gradient(120deg, #1d4ed8, #0ea5e9); border-radius: 16px; padding: 20px; margin-bottom: 18px; }}
    .head h1 {{ margin: 0 0 8px 0; }}
    .head .meta {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 20px; }}
    .search {{ margin: 12px 0 16px 0; }}
    input[type="search"] {{
      width: 100%;
      padding: 12px 14px;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: #0f172a;
      color: var(--text);
      font-size: 15px;
    }}
    .card {{ background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 16px; margin-bottom: 14px; }}
    .meta {{ display: flex; align-items: center; gap: 10px; }}
    .idx {{ color: var(--accent); font-weight: 700; min-width: 56px; }}
    h2 {{ margin: 0; font-size: 22px; }}
    .badge {{ margin-left: auto; padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: 700; }}
    .badge.active {{ background: #063b2e; color: #86efac; border: 1px solid #14532d; }}
    .badge.inactive {{ background: #3f1d1d; color: #fca5a5; border: 1px solid #7f1d1d; }}
    .sub {{ margin: 8px 0 10px 0; color: var(--muted); }}
    .prompt-wrap {{ background: #0f172a; border: 1px solid #1e293b; border-radius: 12px; overflow: hidden; }}
    .prompt-title {{ padding: 10px 12px; color: #93c5fd; border-bottom: 1px solid #1e293b; font-size: 14px; }}
    pre {{ margin: 0; padding: 14px; white-space: pre-wrap; word-break: break-word; font-size: 13px; line-height: 1.45; }}
    code {{ color: #bfdbfe; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="head">
      <h1>Trends Prompts Export</h1>
      <div class="meta">
        <div><b>Generated:</b> {html.escape(now_iso)}</div>
        <div><b>Total trends:</b> {len(items)}</div>
      </div>
    </div>

    <div class="search">
      <input id="q" type="search" placeholder="Фильтр по названию/ID/тексту prompt..." />
    </div>

    <div id="list">
      {''.join(cards)}
    </div>
  </div>
  <script>
    const q = document.getElementById('q');
    const cards = Array.from(document.querySelectorAll('.card'));
    q.addEventListener('input', () => {{
      const v = q.value.toLowerCase().trim();
      for (const c of cards) {{
        c.style.display = c.innerText.toLowerCase().includes(v) ? '' : 'none';
      }}
    }});
  </script>
</body>
</html>
"""

    (out_dir / "report.html").write_text(html_doc, encoding="utf-8")
    (out_dir / "report.json").write_text(
        json.dumps(
            {
                "generated_at": now_iso,
                "count": len(items),
                "release_prompt_input": prompt_input,
                "release_prompt_task": "",
                "rows": items,
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
