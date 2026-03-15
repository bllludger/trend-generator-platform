"""
Prometheus-based metrics for production monitoring.
Provides /metrics endpoint for scraping.
"""
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from fastapi import APIRouter, Response


# Counters
jobs_created_total = Counter(
    "jobs_created_total",
    "Total number of jobs created",
    ["trend_id"],
)

jobs_succeeded_total = Counter(
    "jobs_succeeded_total",
    "Total number of successful jobs",
    ["trend_id"],
)

jobs_failed_total = Counter(
    "jobs_failed_total",
    "Total number of failed jobs",
    ["trend_id", "error_code"],
)

token_operations_total = Counter(
    "token_operations_total",
    "Total token ledger operations",
    ["operation"],  # HOLD, CAPTURE, RELEASE
)

balance_rejected_total = Counter(
    "balance_rejected_total",
    "Total balance rejections",
)

telegram_requests_total = Counter(
    "telegram_requests_total",
    "Total Telegram API requests",
    ["method", "status"],
)

openai_requests_total = Counter(
    "openai_requests_total",
    "Total OpenAI API requests",
    ["status"],
)

circuit_breaker_state = Gauge(
    "circuit_breaker_state",
    "Circuit breaker state (0=closed, 1=open)",
    ["name"],
)

# Histograms
job_duration_seconds = Histogram(
    "job_duration_seconds",
    "Job processing duration",
    ["trend_id"],
    buckets=[1, 5, 10, 30, 60, 120, 300],
)

telegram_request_duration_seconds = Histogram(
    "telegram_request_duration_seconds",
    "Telegram API request duration",
    ["method"],
    buckets=[0.1, 0.5, 1, 2, 5, 10],
)

openai_request_duration_seconds = Histogram(
    "openai_request_duration_seconds",
    "OpenAI API request duration",
    buckets=[1, 5, 10, 30, 60, 120],
)

# Gauges
active_jobs = Gauge(
    "active_jobs",
    "Currently running jobs",
)

queue_length = Gauge(
    "queue_length",
    "Current queue length",
)

# --- HTTP / API ---
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration",
    ["method", "path"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
)

api_health_check_failures_total = Counter(
    "api_health_check_failures_total",
    "Health/ready check failures",
)

# --- Generation (Take / Job / Image / HD) ---
takes_created_total = Counter(
    "takes_created_total",
    "Total takes created (main flow)",
)

takes_completed_total = Counter(
    "takes_completed_total",
    "Total takes completed (ready/partial_fail)",
)

takes_failed_total = Counter(
    "takes_failed_total",
    "Total takes failed",
)

take_generation_duration_seconds = Histogram(
    "take_generation_duration_seconds",
    "Time from take creation to previews ready",
    buckets=[10, 30, 60, 90, 120, 180, 300],
)

image_generation_requests_total = Counter(
    "image_generation_requests_total",
    "Image provider calls by outcome",
    ["provider", "status"],  # status: ok, fail
)

image_generation_duration_seconds = Histogram(
    "image_generation_duration_seconds",
    "Image generation latency (generate_with_retry)",
    ["provider"],
    buckets=[5, 15, 30, 45, 60, 90, 120, 180],
)

image_generation_retries_total = Counter(
    "image_generation_retries_total",
    "Image generation retries by failure type",
    ["failure_type"],
)

favorites_hd_delivery_total = Counter(
    "favorites_hd_delivery_total",
    "HD delivery outcome (delivered, failed, skipped)",
    ["outcome"],
)

favorites_hd_stuck_rendering_reset_total = Counter(
    "favorites_hd_stuck_rendering_reset_total",
    "Stuck rendering resets by watchdog",
)

# --- Payments ---
pay_initiated_total = Counter(
    "pay_initiated_total",
    "Payment initiated (pre_checkout or button)",
    ["pack_id"],
)

pay_pre_checkout_rejected_total = Counter(
    "pay_pre_checkout_rejected_total",
    "pre_checkout_query rejected",
    ["reason"],
)

pay_success_total = Counter(
    "pay_success_total",
    "Successful payment",
    ["pack_id", "payment_method"],
)

payment_amount_stars_total = Counter(
    "payment_amount_stars_total",
    "Total stars received (pay_success)",
    ["pack_id"],
)

payment_processing_errors_total = Counter(
    "payment_processing_errors_total",
    "Payment processing errors (credit_tokens etc)",
    ["reason"],
)

pay_refund_total = Counter(
    "pay_refund_total",
    "Refunds by reason",
    ["reason"],
)

# --- Funnel / User flow ---
bot_started_total = Counter(
    "bot_started_total",
    "Bot /start or first entry",
)

photo_uploaded_total = Counter(
    "photo_uploaded_total",
    "Photo uploaded (session/format)",
)

take_previews_ready_total = Counter(
    "take_previews_ready_total",
    "Take with 3 previews ready",
)

favorite_selected_total = Counter(
    "favorite_selected_total",
    "User selected variant A/B/C",
)

paywall_viewed_total = Counter(
    "paywall_viewed_total",
    "Paywall shown (unlock or pack)",
)

# --- Telemetry / Admin ---
product_events_track_total = Counter(
    "product_events_track_total",
    "ProductAnalyticsService.track calls",
    ["event_name", "status"],  # status: ok, db_error
)

admin_api_requests_total = Counter(
    "admin_api_requests_total",
    "Requests to /admin/*",
    ["path", "status"],
)

admin_grant_pack_total = Counter(
    "admin_grant_pack_total",
    "Admin grant-pack operations",
    ["status"],  # success, failure, idempotent_replay
)

admin_reset_limits_total = Counter(
    "admin_reset_limits_total",
    "Admin reset-limits operations",
    ["status"],  # success, no_change, failure
)

# --- Errors ---
generation_failed_total = Counter(
    "generation_failed_total",
    "Generation failed by error_code and source",
    ["error_code", "source"],  # source: take, job
)

telegram_send_failures_total = Counter(
    "telegram_send_failures_total",
    "Telegram send message/photo failures",
    ["method"],
)

hd_delivery_failed_total = Counter(
    "hd_delivery_failed_total",
    "HD delivery failed (file or Telegram error)",
)

# --- Celery queue (updated from API or exporter) ---
celery_queue_length = Gauge(
    "celery_queue_length",
    "Celery queue length",
    ["queue"],
)

celery_active_tasks = Gauge(
    "celery_active_tasks",
    "Currently running Celery tasks",
    ["task_name"],
)


# Metrics endpoint router
router = APIRouter()


# Таймауты для Redis при обновлении очередей, чтобы /metrics не блокировался при недоступности broker
_CELERY_QUEUE_REDIS_TIMEOUT = 2.0


def _update_celery_queue_gauges() -> None:
    """Update celery_queue_length from Redis broker. No-op on error; uses short timeouts to avoid blocking /metrics."""
    try:
        from app.core.config import settings
        import redis as redis_client
        r = redis_client.Redis.from_url(
            settings.celery_broker_url,
            decode_responses=False,
            socket_connect_timeout=_CELERY_QUEUE_REDIS_TIMEOUT,
            socket_timeout=_CELERY_QUEUE_REDIS_TIMEOUT,
        )
        for queue_name in ("celery", "generation"):
            try:
                length = r.llen(queue_name)
                celery_queue_length.labels(queue=queue_name).set(length)
            except Exception:
                celery_queue_length.labels(queue=queue_name).set(-1)
        r.close()
    except Exception:
        pass


@router.get("/metrics")
def metrics_endpoint() -> Response:
    """Prometheus metrics endpoint for scraping."""
    _update_celery_queue_gauges()
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


# Legacy compatibility wrapper (for gradual migration)
class MetricsCompat:
    """Backward-compatible wrapper for legacy code."""
    
    @property
    def jobs_created(self) -> int:
        return 0  # Use Prometheus counter directly
    
    @jobs_created.setter
    def jobs_created(self, value: int) -> None:
        pass  # No-op, use inc() instead

    def inc_jobs_created(self, trend_id: str = "unknown") -> None:
        jobs_created_total.labels(trend_id=trend_id).inc()

    def inc_jobs_succeeded(self, trend_id: str = "unknown") -> None:
        jobs_succeeded_total.labels(trend_id=trend_id).inc()

    def inc_jobs_failed(self, trend_id: str = "unknown", error_code: str = "unknown") -> None:
        jobs_failed_total.labels(trend_id=trend_id, error_code=error_code).inc()

    def inc_token_hold(self) -> None:
        token_operations_total.labels(operation="HOLD").inc()

    def inc_token_capture(self) -> None:
        token_operations_total.labels(operation="CAPTURE").inc()

    def inc_token_release(self) -> None:
        token_operations_total.labels(operation="RELEASE").inc()

    def inc_balance_rejected(self) -> None:
        balance_rejected_total.inc()


metrics = MetricsCompat()
