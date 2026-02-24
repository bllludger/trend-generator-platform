"""
Circuit breaker implementation using pybreaker library.
Provides Redis-backed state storage for distributed systems.
"""
import functools
import logging
import redis
import pybreaker
from typing import Callable, Any

from app.core.config import settings
from app.utils.metrics import circuit_breaker_state


logger = logging.getLogger("circuit_breaker")


class RedisCircuitBreakerStorage(pybreaker.CircuitBreakerStorage):
    """Redis-backed storage for circuit breaker state (distributed-friendly)."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._name = name
        self.client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        self._state_key = f"cb:{name}:state"
        self._counter_key = f"cb:{name}:counter"

    @property
    def state(self) -> str:
        state = self.client.get(self._state_key)
        return state or pybreaker.STATE_CLOSED

    @state.setter
    def state(self, value: str) -> None:
        self.client.set(self._state_key, value, ex=settings.cb_open_seconds * 2)
        # Update Prometheus gauge
        circuit_breaker_state.labels(name=self._name).set(
            1 if value == pybreaker.STATE_OPEN else 0
        )

    @property
    def counter(self) -> int:
        count = self.client.get(self._counter_key)
        return int(count) if count else 0

    @counter.setter
    def counter(self, value: int) -> None:
        self.client.set(self._counter_key, str(value), ex=settings.cb_open_seconds)

    def increment_counter(self) -> None:
        self.client.incr(self._counter_key)
        self.client.expire(self._counter_key, settings.cb_open_seconds)

    def reset(self) -> None:
        self.client.delete(self._counter_key)


class CircuitBreakerListener(pybreaker.CircuitBreakerListener):
    """Listener for circuit breaker events (logging/metrics)."""

    def __init__(self, name: str) -> None:
        self.name = name

    def state_change(self, cb: pybreaker.CircuitBreaker, old_state: str, new_state: str) -> None:
        logger.warning(
            "circuit_breaker_state_change",
            extra={
                "breaker_name": self.name,
                "old_state": old_state,
                "new_state": new_state,
            },
        )

    def failure(self, cb: pybreaker.CircuitBreaker, exc: Exception) -> None:
        logger.warning(
            "circuit_breaker_failure",
            extra={
                "breaker_name": self.name,
                "error": type(exc).__name__,
            },
        )


# Pre-configured circuit breakers
_breakers: dict[str, pybreaker.CircuitBreaker] = {}


def get_circuit_breaker(name: str) -> pybreaker.CircuitBreaker:
    """Get or create a circuit breaker by name."""
    if name not in _breakers:
        _breakers[name] = pybreaker.CircuitBreaker(
            fail_max=settings.cb_failure_threshold,
            reset_timeout=settings.cb_open_seconds,
            state_storage=RedisCircuitBreakerStorage(name),
            listeners=[CircuitBreakerListener(name)],
        )
    return _breakers[name]


# Convenience instances
openai_breaker = get_circuit_breaker("openai")
# For all image generation providers (OpenAI, Gemini, etc.)
image_provider_breaker = get_circuit_breaker("image_provider")


def with_circuit_breaker(breaker: pybreaker.CircuitBreaker) -> Callable:
    """Decorator to wrap function with circuit breaker."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return breaker.call(func, *args, **kwargs)
        return wrapper
    return decorator


# Legacy compatibility
class CircuitBreaker:
    """Legacy wrapper for backward compatibility."""

    def __init__(self, name: str) -> None:
        self.breaker = get_circuit_breaker(name)

    def allow(self) -> bool:
        return self.breaker.current_state != pybreaker.STATE_OPEN

    def record_success(self) -> None:
        pass  # pybreaker handles this automatically

    def record_failure(self) -> None:
        pass  # pybreaker handles this automatically

    def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        return self.breaker.call(func, *args, **kwargs)
