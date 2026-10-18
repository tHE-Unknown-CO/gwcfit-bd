from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock


@dataclass(frozen=True)
class RuntimeMetricsSnapshot:
    started_at: datetime
    request_count: int
    error_count: int
    average_latency_ms: float | None
    uptime_seconds: int


class RuntimeMetrics:
    """Bounded, process-local request telemetry for the live API worker."""

    def __init__(self, latency_window: int = 2_000) -> None:
        self._started_at = datetime.now(UTC)
        self._request_count = 0
        self._error_count = 0
        self._latencies_ms: deque[float] = deque(maxlen=latency_window)
        self._lock = Lock()

    def record_request(self, latency_ms: float, status_code: int) -> None:
        with self._lock:
            self._request_count += 1
            if status_code >= 500:
                self._error_count += 1
            self._latencies_ms.append(max(0.0, latency_ms))

    def snapshot(self) -> RuntimeMetricsSnapshot:
        with self._lock:
            average_latency_ms = (
                round(sum(self._latencies_ms) / len(self._latencies_ms), 2)
                if self._latencies_ms
                else None
            )
            request_count = self._request_count
            error_count = self._error_count

        uptime_seconds = max(0, int((datetime.now(UTC) - self._started_at).total_seconds()))
        return RuntimeMetricsSnapshot(
            started_at=self._started_at,
            request_count=request_count,
            error_count=error_count,
            average_latency_ms=average_latency_ms,
            uptime_seconds=uptime_seconds,
        )


runtime_metrics = RuntimeMetrics()
