#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "data" / "as_is_analytics_snapshot"
API_CONTAINER = "ai_slop_2-api-1"
DB_CONTAINER = "ai_slop_2-db-1"
API_BASE = "http://127.0.0.1:8000"


@dataclass
class MetricRow:
    area: str
    window: str
    metric_name: str
    metric_value: Any
    source: str
    notes: str = ""


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


ENV = load_env_file(ROOT / ".env")
ADMIN_USERNAME = ENV["ADMIN_UI_USERNAME"]
ADMIN_PASSWORD = ENV["ADMIN_UI_PASSWORD"]


def run(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True)


def docker_exec(container: str, shell_cmd: str) -> str:
    return run(["docker", "exec", container, "sh", "-lc", shell_cmd])


def api_login() -> str:
    payload = json.dumps({"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
    output = docker_exec(
        API_CONTAINER,
        "curl -sS -X POST "
        f"{API_BASE}/admin/auth/login "
        "-H 'Content-Type: application/json' "
        f"-d '{payload}'",
    )
    return json.loads(output)["access_token"]


def api_get(token: str, path: str) -> Any:
    output = docker_exec(
        API_CONTAINER,
        f"curl -sS -H 'Authorization: Bearer {token}' '{API_BASE}{path}'",
    )
    return json.loads(output)


def psql_csv(sql: str) -> list[dict[str, str]]:
    output = run(
        [
            "docker",
            "exec",
            DB_CONTAINER,
            "psql",
            "-U",
            "trends",
            "-d",
            "trends",
            "--csv",
            "-P",
            "pager=off",
            "-c",
            sql,
        ]
    )
    return list(csv.DictReader(output.splitlines()))


def flatten_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def markdown_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    if not rows:
        return "_Нет данных_"
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join(["---"] * len(columns)) + " |"
    body = [
        "| " + " | ".join(str(row.get(col, "")) for col in columns) + " |"
        for row in rows
    ]
    return "\n".join([header, sep, *body])


def key_value_rows(payload: dict[str, Any], exclude: set[str] | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, value in payload.items():
        if exclude and key in exclude:
            continue
        if isinstance(value, (dict, list)):
            continue
        rows.append({"metric": key, "value": value})
    return rows


def add_map_metrics(
    rows: list[MetricRow],
    *,
    area: str,
    window: str,
    prefix: str,
    mapping: dict[str, Any] | None,
    source: str,
    notes: str = "",
) -> None:
    if not mapping:
        return
    for key, value in mapping.items():
        rows.append(
            MetricRow(
                area=area,
                window=window,
                metric_name=f"{prefix}.{key}",
                metric_value=value,
                source=source,
                notes=notes,
            )
        )


def build_users_export(token: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    first_page = api_get(token, "/admin/users?page=1&page_size=200&sort_by=created_at&sort_order=desc")
    total_pages = int(first_page.get("pages") or 1)
    items = list(first_page.get("items") or [])
    for page in range(2, total_pages + 1):
        payload = api_get(
            token,
            f"/admin/users?page={page}&page_size=200&sort_by=created_at&sort_order=desc",
        )
        items.extend(payload.get("items") or [])
    flattened: list[dict[str, Any]] = []
    for item in items:
        active = item.get("active_session") or {}
        flattened.append(
            {
                "id": item.get("id"),
                "telegram_id": item.get("telegram_id"),
                "telegram_username": item.get("telegram_username"),
                "telegram_first_name": item.get("telegram_first_name"),
                "telegram_last_name": item.get("telegram_last_name"),
                "token_balance": item.get("token_balance"),
                "subscription_active": item.get("subscription_active"),
                "free_generations_used": item.get("free_generations_used"),
                "free_generations_limit": item.get("free_generations_limit"),
                "copy_generations_used": item.get("copy_generations_used"),
                "copy_generations_limit": item.get("copy_generations_limit"),
                "trial_purchased": item.get("trial_purchased"),
                "free_takes_used": item.get("free_takes_used"),
                "payments_count": item.get("payments_count"),
                "jobs_count": item.get("jobs_count"),
                "succeeded": item.get("succeeded"),
                "failed": item.get("failed"),
                "last_active": item.get("last_active"),
                "created_at": item.get("created_at"),
                "active_session_pack_id": active.get("pack_id"),
                "active_session_pack_name": active.get("pack_name"),
                "active_session_takes_limit": active.get("takes_limit"),
                "active_session_takes_used": active.get("takes_used"),
                "active_session_takes_remaining": active.get("takes_remaining"),
                "active_session_hd_limit": active.get("hd_limit"),
                "active_session_hd_used": active.get("hd_used"),
                "active_session_hd_remaining": active.get("hd_remaining"),
            }
        )
    return flattened, {"total": first_page.get("total"), "pages": total_pages}


def build_report(payloads: dict[str, Any], table_counts: list[dict[str, str]], users_meta: dict[str, Any]) -> str:
    snapshot_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    users_analytics = payloads["users_analytics_30d"]
    telemetry = payloads["telemetry_dashboard_24h"]
    legacy_metrics = payloads["telemetry_product_metrics_30d"]
    metrics_v2 = payloads["telemetry_product_metrics_v2_7d"]
    funnel = payloads["telemetry_product_funnel_7d"]
    health = payloads["telemetry_health_7d"]
    revenue = payloads["telemetry_revenue_7d"]
    buttons = payloads["telemetry_button_clicks_7d"]
    path = payloads["telemetry_path_7d"]
    payments = payloads["payments_stats_30d"]
    audit_stats = payloads["audit_stats_24h"]
    audit_analytics = payloads["audit_analytics_all"]
    errors = payloads["telemetry_errors_30d"]

    sections = [
        "# AS IS Analytics Snapshot",
        "",
        f"Снимок собран из живых контейнеров `{API_CONTAINER}` и `{DB_CONTAINER}`: **{snapshot_at}**.",
        "",
        "## Артефакты",
        "",
        "- Полная таблица метрик: `docs/data/as_is_analytics_snapshot/all_metrics_flat.csv`",
        "- Полная таблица пользователей: `docs/data/as_is_analytics_snapshot/users_full.csv`",
        "- Raw JSON endpoints: `docs/data/as_is_analytics_snapshot/*.json`",
        "",
        "## 1. Raw DB Footprint",
        "",
        markdown_table(table_counts, ["table_name", "row_count"]),
        "",
        "## 2. Users Analytics 30d",
        "",
        markdown_table(
            key_value_rows(users_analytics["overview"]),
            ["metric", "value"],
        ),
        "",
        "### Рост пользователей по дням",
        "",
        markdown_table(users_analytics.get("growth", []), ["date", "new_users"]),
        "",
        "### Активность пользователей",
        "",
        markdown_table(users_analytics.get("activity_segments", []), ["segment", "users"]),
        "",
        "### Распределение баланса",
        "",
        markdown_table(users_analytics.get("token_distribution", []), ["range", "count"]),
        "",
        "### Топ пользователей по jobs за 30 дней",
        "",
        markdown_table(
            users_analytics.get("top_users", []),
            ["telegram_id", "user_display_name", "jobs_count", "succeeded", "failed", "token_balance"],
        ),
        "",
        f"Всего строк в полном per-user export: **{users_meta.get('total', 0)}**.",
        "",
        "## 3. Telemetry Dashboard 24h",
        "",
        markdown_table(
            key_value_rows(telemetry, exclude={"trend_analytics_window", "variants_chosen_by_trend", "jobs_by_status", "jobs_failed_by_error"}),
            ["metric", "value"],
        ),
        "",
        "### Jobs по статусам за 24 часа",
        "",
        markdown_table(
            [{"status": key, "count": value} for key, value in (telemetry.get("jobs_by_status") or {}).items()],
            ["status", "count"],
        ),
        "",
        "### Top trends за 24 часа",
        "",
        markdown_table(
            (telemetry.get("trend_analytics_window") or [])[:20],
            ["trend_id", "name", "jobs_window", "takes_window", "takes_succeeded_window", "takes_failed_window", "chosen_window"],
        ),
        "",
        "## 4. Product Metrics",
        "",
        "### Legacy product metrics 30d",
        "",
        markdown_table(key_value_rows(legacy_metrics), ["metric", "value"]),
        "",
        "### Product metrics v2 7d",
        "",
        markdown_table(key_value_rows(metrics_v2, exclude={"data_quality"}), ["metric", "value"]),
        "",
        "### Product metrics v2 data quality 7d",
        "",
        markdown_table(
            [{"metric": key, "value": value} for key, value in (metrics_v2.get("data_quality") or {}).items()],
            ["metric", "value"],
        ),
        "",
        "## 5. Funnel / Health / Revenue 7d",
        "",
        "### Funnel counts",
        "",
        markdown_table(
            [
                {
                    "step": step,
                    "legacy": funnel.get("funnel_counts", {}).get(step, 0),
                    "shadow": funnel.get("shadow_funnel_counts", {}).get(step, 0),
                    "diff": funnel.get("diff_funnel_counts", {}).get(step, 0),
                }
                for step in funnel.get("funnel_counts", {}).keys()
            ],
            ["step", "legacy", "shadow", "diff"],
        ),
        "",
        "### Health data quality",
        "",
        markdown_table(
            [{"metric": key, "value": value} for key, value in (health.get("data_quality") or {}).items()],
            ["metric", "value"],
        ),
        "",
        "### Revenue 7d",
        "",
        markdown_table(key_value_rows(revenue, exclude={"by_pack", "by_source", "data_quality", "quality_warnings"}), ["metric", "value"]),
        "",
        "### Revenue by pack 7d",
        "",
        markdown_table(
            [{"pack_id": key, "value": value} for key, value in (revenue.get("by_pack") or {}).items()],
            ["pack_id", "value"],
        ),
        "",
        "### Revenue by source 7d",
        "",
        markdown_table(
            [{"source": key, "value": value} for key, value in (revenue.get("by_source") or {}).items()],
            ["source", "value"],
        ),
        "",
        "### Revenue data quality 7d",
        "",
        markdown_table(
            [{"metric": key, "value": value} for key, value in (revenue.get("data_quality") or {}).items()],
            ["metric", "value"],
        ),
        "",
        "## 6. Buttons / Path 7d",
        "",
        "### Button clicks",
        "",
        markdown_table(
            [{"button_id": key, "clicks": value} for key, value in (buttons.get("by_button_id") or {}).items()],
            ["button_id", "clicks"],
        ),
        "",
        "### Unknown button clicks",
        "",
        markdown_table(
            [{"button_id": key, "clicks": value} for key, value in (buttons.get("unknown_by_button_id") or {}).items()],
            ["button_id", "clicks"],
        ),
        "",
        "### Path transitions",
        "",
        markdown_table(
            path.get("transitions", []),
            ["from", "to", "sessions", "median_minutes", "avg_minutes"],
        ),
        "",
        "### Path drop-off",
        "",
        markdown_table(
            path.get("drop_off", []),
            ["from", "to", "sessions", "median_minutes", "avg_minutes"],
        ),
        "",
        "### Path sequences",
        "",
        markdown_table(
            [
                {
                    "steps": " -> ".join(item.get("steps", [])),
                    "sessions": item.get("sessions"),
                    "median_minutes_to_pay": item.get("median_minutes_to_pay"),
                    "median_minutes_to_last": item.get("median_minutes_to_last"),
                    "pct_reached_pay": item.get("pct_reached_pay"),
                }
                for item in path.get("paths", [])
            ],
            ["steps", "sessions", "median_minutes_to_pay", "median_minutes_to_last", "pct_reached_pay"],
        ),
        "",
        "## 7. Payments / Audit / Errors",
        "",
        "### Payments stats 30d",
        "",
        markdown_table(key_value_rows(payments, exclude={"by_pack"}), ["metric", "value"]),
        "",
        "### Payments by pack 30d",
        "",
        markdown_table(payments.get("by_pack", []), ["pack_id", "count", "stars", "rub"]),
        "",
        "### Audit stats 24h",
        "",
        markdown_table(key_value_rows(audit_stats, exclude={"by_actor_type"}), ["metric", "value"]),
        "",
        "### Audit by actor type 24h",
        "",
        markdown_table(
            [{"actor_type": key, "count": value} for key, value in (audit_stats.get("by_actor_type") or {}).items()],
            ["actor_type", "count"],
        ),
        "",
        "### Audit actions all time",
        "",
        markdown_table(
            [{"action": key, "count": value} for key, value in (audit_analytics.get("by_action") or {}).items()],
            ["action", "count"],
        ),
        "",
        "### Errors 30d combined",
        "",
        markdown_table(
            [{"error_code": key, "count": value} for key, value in (errors.get("combined") or {}).items()],
            ["error_code", "count"],
        ),
    ]
    return "\n".join(sections) + "\n"


def build_flat_metrics(
    payloads: dict[str, Any],
    table_counts: list[dict[str, str]],
) -> list[dict[str, Any]]:
    rows: list[MetricRow] = []

    for row in table_counts:
        rows.append(
            MetricRow(
                area="db",
                window="all_time",
                metric_name=f"table_count.{row['table_name']}",
                metric_value=row["row_count"],
                source="db.table_counts.json",
            )
        )

    users_analytics = payloads["users_analytics_30d"]
    for key, value in users_analytics.get("overview", {}).items():
        rows.append(MetricRow("users", "30d", key, value, "users_analytics_30d.json"))
    for item in users_analytics.get("growth", []):
        rows.append(
            MetricRow(
                "users",
                "30d",
                f"growth_new_users.{item.get('date')}",
                item.get("new_users"),
                "users_analytics_30d.json",
            )
        )
    for item in users_analytics.get("activity_segments", []):
        rows.append(
            MetricRow(
                "users",
                "30d",
                f"activity_segment.{item.get('segment')}",
                item.get("users"),
                "users_analytics_30d.json",
            )
        )
    for item in users_analytics.get("token_distribution", []):
        rows.append(
            MetricRow(
                "users",
                "all_time",
                f"token_distribution.{item.get('range')}",
                item.get("count"),
                "users_analytics_30d.json",
            )
        )

    telemetry = payloads["telemetry_dashboard_24h"]
    for key, value in telemetry.items():
        if isinstance(value, (dict, list)):
            continue
        rows.append(MetricRow("telemetry_dashboard", "24h", key, value, "telemetry_dashboard_24h.json"))
    add_map_metrics(
        rows,
        area="telemetry_dashboard",
        window="24h",
        prefix="jobs_by_status",
        mapping=telemetry.get("jobs_by_status"),
        source="telemetry_dashboard_24h.json",
    )
    add_map_metrics(
        rows,
        area="telemetry_dashboard",
        window="24h",
        prefix="jobs_failed_by_error",
        mapping=telemetry.get("jobs_failed_by_error"),
        source="telemetry_dashboard_24h.json",
    )
    for trend in telemetry.get("trend_analytics_window", []):
        rows.append(
            MetricRow(
                "telemetry_dashboard",
                "24h",
                f"trend_activity.{trend.get('trend_id')}",
                json.dumps(trend, ensure_ascii=False, sort_keys=True),
                "telemetry_dashboard_24h.json",
                notes=trend.get("name", ""),
            )
        )

    for name in ("telemetry_product_metrics_30d", "telemetry_product_metrics_v2_7d", "telemetry_health_7d", "telemetry_revenue_7d"):
        area = name.replace("_30d", "").replace("_7d", "")
        window = "30d" if name.endswith("_30d") else "7d"
        payload = payloads[name]
        for key, value in payload.items():
            if isinstance(value, (dict, list)):
                continue
            rows.append(MetricRow(area, window, key, value, f"{name}.json"))
        for key in ("data_quality", "metrics", "by_pack", "by_source"):
            if isinstance(payload.get(key), dict):
                add_map_metrics(
                    rows,
                    area=area,
                    window=window,
                    prefix=key,
                    mapping=payload.get(key),
                    source=f"{name}.json",
                )

    funnel = payloads["telemetry_product_funnel_7d"]
    for prefix in ("funnel_counts", "shadow_funnel_counts", "diff_funnel_counts"):
        add_map_metrics(
            rows,
            area="funnel",
            window="7d",
            prefix=prefix,
            mapping=funnel.get(prefix),
            source="telemetry_product_funnel_7d.json",
        )
    add_map_metrics(
        rows,
        area="funnel",
        window="7d",
        prefix="data_quality",
        mapping=funnel.get("data_quality"),
        source="telemetry_product_funnel_7d.json",
    )

    buttons = payloads["telemetry_button_clicks_7d"]
    add_map_metrics(
        rows,
        area="buttons",
        window="7d",
        prefix="by_button_id",
        mapping=buttons.get("by_button_id"),
        source="telemetry_button_clicks_7d.json",
    )
    add_map_metrics(
        rows,
        area="buttons",
        window="7d",
        prefix="unknown_by_button_id",
        mapping=buttons.get("unknown_by_button_id"),
        source="telemetry_button_clicks_7d.json",
    )

    path = payloads["telemetry_path_7d"]
    for item in path.get("transitions", []):
        rows.append(
            MetricRow(
                "path",
                "7d",
                f"transition.{item.get('from')}->{item.get('to')}",
                item.get("sessions"),
                "telemetry_path_7d.json",
                notes=json.dumps(
                    {
                        "median_minutes": item.get("median_minutes"),
                        "avg_minutes": item.get("avg_minutes"),
                    },
                    ensure_ascii=False,
                ),
            )
        )
    for item in path.get("drop_off", []):
        rows.append(
            MetricRow(
                "path",
                "7d",
                f"drop_off.{item.get('from')}",
                item.get("sessions"),
                "telemetry_path_7d.json",
                notes=json.dumps(
                    {
                        "median_minutes": item.get("median_minutes"),
                        "avg_minutes": item.get("avg_minutes"),
                    },
                    ensure_ascii=False,
                ),
            )
        )

    payments = payloads["payments_stats_30d"]
    for key, value in payments.items():
        if isinstance(value, (dict, list)):
            continue
        rows.append(MetricRow("payments", "30d", key, value, "payments_stats_30d.json"))
    for item in payments.get("by_pack", []):
        rows.append(
            MetricRow(
                "payments",
                "30d",
                f"by_pack.{item.get('pack_id')}",
                json.dumps(item, ensure_ascii=False, sort_keys=True),
                "payments_stats_30d.json",
            )
        )

    audit_stats = payloads["audit_stats_24h"]
    for key, value in audit_stats.items():
        if isinstance(value, (dict, list)):
            continue
        rows.append(MetricRow("audit", "24h", key, value, "audit_stats_24h.json"))
    add_map_metrics(
        rows,
        area="audit",
        window="24h",
        prefix="by_actor_type",
        mapping=audit_stats.get("by_actor_type"),
        source="audit_stats_24h.json",
    )
    add_map_metrics(
        rows,
        area="audit",
        window="all_time",
        prefix="by_action",
        mapping=payloads["audit_analytics_all"].get("by_action"),
        source="audit_analytics_all.json",
    )

    errors = payloads["telemetry_errors_30d"]
    add_map_metrics(
        rows,
        area="errors",
        window="30d",
        prefix="combined",
        mapping=errors.get("combined"),
        source="telemetry_errors_30d.json",
    )

    return [
        {
            "area": row.area,
            "window": row.window,
            "metric_name": row.metric_name,
            "metric_value": flatten_value(row.metric_value),
            "source": row.source,
            "notes": row.notes,
        }
        for row in rows
    ]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    token = api_login()

    endpoint_map = {
        "users_analytics_30d": "/admin/users/analytics?time_window=30",
        "telemetry_dashboard_24h": "/admin/telemetry?window_hours=24",
        "telemetry_history_30d": "/admin/telemetry/history?window_days=30",
        "telemetry_product_metrics_30d": "/admin/telemetry/product-metrics?window_days=30",
        "telemetry_product_funnel_7d": "/admin/telemetry/product-funnel?window_days=7",
        "telemetry_product_funnel_history_7d": "/admin/telemetry/product-funnel-history?window_days=7",
        "telemetry_button_clicks_7d": "/admin/telemetry/button-clicks?window_days=7",
        "telemetry_product_metrics_v2_7d": "/admin/telemetry/product-metrics-v2?window_days=7",
        "telemetry_revenue_7d": "/admin/telemetry/revenue?window_days=7",
        "telemetry_health_7d": "/admin/telemetry/health?window_days=7",
        "telemetry_errors_30d": "/admin/telemetry/errors?window_days=30",
        "telemetry_path_7d": "/admin/telemetry/path?window_days=7&limit=20",
        "payments_stats_30d": "/admin/payments/stats?days=30",
        "audit_stats_24h": "/admin/audit/stats?window_hours=24",
        "audit_analytics_all": "/admin/audit/analytics",
    }

    payloads = {name: api_get(token, path) for name, path in endpoint_map.items()}
    for name, payload in payloads.items():
        write_json(OUT_DIR / f"{name}.json", payload)

    table_counts = psql_csv(
        """
        select 'audit_logs' as table_name, count(*)::text as row_count from audit_logs
        union all select 'bank_transfer_receipt_log', count(*)::text from bank_transfer_receipt_log
        union all select 'favorites', count(*)::text from favorites
        union all select 'jobs', count(*)::text from jobs
        union all select 'pack_orders', count(*)::text from pack_orders
        union all select 'payments', count(*)::text from payments
        union all select 'referral_bonuses', count(*)::text from referral_bonuses
        union all select 'sessions', count(*)::text from sessions
        union all select 'takes', count(*)::text from takes
        union all select 'users', count(*)::text from users
        order by table_name;
        """
    )
    write_json(OUT_DIR / "db_table_counts.json", table_counts)

    users_rows, users_meta = build_users_export(token)
    write_csv(
        OUT_DIR / "users_full.csv",
        users_rows,
        [
            "id",
            "telegram_id",
            "telegram_username",
            "telegram_first_name",
            "telegram_last_name",
            "token_balance",
            "subscription_active",
            "free_generations_used",
            "free_generations_limit",
            "copy_generations_used",
            "copy_generations_limit",
            "trial_purchased",
            "free_takes_used",
            "payments_count",
            "jobs_count",
            "succeeded",
            "failed",
            "last_active",
            "created_at",
            "active_session_pack_id",
            "active_session_pack_name",
            "active_session_takes_limit",
            "active_session_takes_used",
            "active_session_takes_remaining",
            "active_session_hd_limit",
            "active_session_hd_used",
            "active_session_hd_remaining",
        ],
    )
    write_json(OUT_DIR / "users_full_meta.json", users_meta)

    flat_metrics = build_flat_metrics(payloads, table_counts)
    write_csv(
        OUT_DIR / "all_metrics_flat.csv",
        flat_metrics,
        ["area", "window", "metric_name", "metric_value", "source", "notes"],
    )

    report = build_report(payloads, table_counts, users_meta)
    (OUT_DIR / "AS_IS_ANALYTICS_SNAPSHOT.md").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
