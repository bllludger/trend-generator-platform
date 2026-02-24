import json
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone

from app.core.config import settings


class JsonFormatter(logging.Formatter):
    """JSON log formatter with support for extra fields."""
    
    # Fields to extract from log record's extra dict
    EXTRA_FIELDS = (
        "job_id", "user_id", "request_id", "path", "method", 
        "status_code", "latency_ms", "trend_id", "error", "chat_id",
        "breaker_name", "old_state", "new_state",
    )
    
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Extract extra fields from record
        for field in self.EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        
        # Include exception info if present
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    formatter = JsonFormatter()
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    handlers = [handler]
    if settings.log_file:
        file_handler = RotatingFileHandler(
            settings.log_file,
            maxBytes=settings.log_max_bytes,
            backupCount=settings.log_backup_count,
        )
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)
    root.handlers = handlers
