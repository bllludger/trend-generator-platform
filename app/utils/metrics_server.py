"""
Minimal HTTP server for Prometheus /metrics in non-FastAPI processes (bot, Celery worker).
Runs in a background daemon thread so Prometheus can scrape metrics from bot and workers.
"""
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

logger = logging.getLogger(__name__)


class _MetricsHandler(BaseHTTPRequestHandler):
    """Serves GET /metrics with Prometheus exposition format."""

    def do_GET(self) -> None:
        if self.path == "/metrics" or self.path == "/metrics/":
            try:
                output = generate_latest()
                self.send_response(200)
                self.send_header("Content-Type", CONTENT_TYPE_LATEST)
                self.send_header("Content-Length", str(len(output)))
                self.end_headers()
                self.wfile.write(output)
            except Exception as e:
                logger.warning("Failed to generate metrics: %s", e)
                self.send_response(500)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        """Suppress default request logging to avoid noise."""
        pass


def start_metrics_http_server(port: int = 9091, host: str = "0.0.0.0") -> None:
    """
    Start a daemon thread that serves /metrics on the given port.
    Use different ports for bot (e.g. 8002) and worker (e.g. 9091) when both run on same host.
    """
    server = HTTPServer((host, port), _MetricsHandler)

    def run() -> None:
        try:
            server.serve_forever()
        except Exception as e:
            logger.warning("Metrics server stopped: %s", e)
        finally:
            try:
                server.server_close()
            except Exception:
                pass

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    logger.info("Metrics server listening on %s:%s", host, port)
