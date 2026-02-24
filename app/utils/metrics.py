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


# Metrics endpoint router
router = APIRouter()


@router.get("/metrics")
def metrics_endpoint() -> Response:
    """Prometheus metrics endpoint for scraping."""
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
